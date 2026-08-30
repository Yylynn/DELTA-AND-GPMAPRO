"""Pre-registered DELTA x GPMAPRO short-horizon research protocol.

This module intentionally does not reuse the legacy signal backtest's DELTA
window (which was an explanatory action window).  A DELTA flag is true only
when a forecast was published before the relevant daily close and that close
falls inside the forecast's own window.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable

import numpy as np
import pandas as pd

from app.services.gpmaapro_engine import GpmaAproEngine
from app.services.gpmapro_engine import GpmaProEngine
from app.services.research_metadata import dataframe_identity, provenance_sha256, research_run_metadata
from app.services.strategy_lab import StrategyLabService

PROTOCOL_ID = "US_ETF_SHORT_V1"
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "TLT")
LOOKBACKS = (0, 1, 2, 3, 5)
HORIZONS = (1, 3, 5)
COST_SCENARIOS = (5.0, 10.0, 20.0)

V1_ENTRIES = ("B1", "B2", "B3", "ANY_B", "BOTTOM_FACE", "BOTTOM_2", "BOTTOM_3", "ANY_BOTTOM")
V2_ENTRIES = ("B01", "B02", "B03", "B11", "B12", "B3", "B4", "ANY_B", "BOTTOM_1", "BOTTOM_2", "ANY_BOTTOM")


@dataclass(frozen=True)
class SignalRuleSpec:
    """The immutable, serialisable definition used by every research path."""

    indicator_version: str
    entry_anchor: str
    delta_direction: str | None = None
    delta_lookback: int | None = None
    exit_rule: str = "FIXED"
    exit_anchor: str | None = None
    holding_days: int = 5
    cost_bps_per_side: float = 10.0
    formula_version: str = "GPMAPRO_DISPLAY_BOOL + AI_ITD_CAUSAL_V1"
    data_snapshot_hash: str | None = None

    @property
    def id(self) -> str:
        delta = "NONE" if self.delta_direction is None else f"{self.delta_direction}_{self.delta_lookback}"
        return f"{self.indicator_version}:{self.entry_anchor}:{delta}:{self.exit_rule}:{self.exit_anchor or '-'}:{self.holding_days}:{self.cost_bps_per_side:g}"


def _cluster(flag: pd.Series) -> pd.Series:
    active = flag.fillna(False).astype(bool)
    return active & ~active.shift(1, fill_value=False)


def _recent(flag: pd.Series, lookback: int) -> pd.Series:
    return flag.fillna(False).astype(int).rolling(lookback + 1, min_periods=1).max().astype(bool)


def _normal_pvalue(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


class SignalRuleResearchService:
    """One signal -> order -> fill -> position -> metrics path for both formulas."""

    def __init__(self, *, random_seed: int = 20260824, bootstrap_samples: int = 400):
        self.random_seed = random_seed
        self.bootstrap_samples = bootstrap_samples
        self.v1 = GpmaProEngine()
        self.v2 = GpmaAproEngine()

    def _features(self, bars: pd.DataFrame, version: str) -> tuple[pd.DataFrame, list[dict]]:
        data = (self.v1 if version == "1.0" else self.v2).calculate(bars).copy().reset_index(drop=True)
        data["date"] = pd.to_datetime(data["date"])
        # Use the causal DELTA forecast replay shared with the strategy lab;
        # importantly, do not use its historical 10-day action-window feature.
        replay = StrategyLabService()
        forecasts = replay._delta_forecasts(data)
        low, high = replay._active_delta_flags([pd.Timestamp(x).date() for x in data.date], forecasts)
        data["delta_low"] = low.to_numpy(dtype=bool)
        data["delta_high"] = high.to_numpy(dtype=bool)
        return data, forecasts

    @staticmethod
    def _signal_map(data: pd.DataFrame, version: str) -> dict[str, pd.Series]:
        def any_of(names: Iterable[str]) -> pd.Series:
            return data[list(names)].any(axis=1)
        if version == "1.0":
            result = {name.upper(): data[name].astype(bool) for name in ("b1", "b2", "b3", "bottom_face", "bottom_2", "bottom_3", "top_face", "top_2", "top_3", "s1", "s2")}
            result.update({"ANY_B": any_of(("b1", "b2", "b3")), "ANY_BOTTOM": any_of(("bottom_face", "bottom_2", "bottom_3")), "ANY_S": any_of(("s1", "s2")), "ANY_TOP": any_of(("top_face", "top_2", "top_3"))})
            return result
        result = {name.upper(): data[name].astype(bool) for name in ("b01", "b02", "b03", "b11", "b12", "b3", "b4", "s01", "s02", "s11", "s12", "s2", "s22", "bottom_1", "bottom_2", "top_1", "top_2")}
        result.update({"ANY_B": any_of(("b01", "b02", "b03", "b11", "b12", "b3", "b4")), "ANY_BOTTOM": any_of(("bottom_1", "bottom_2")), "ANY_S": any_of(("s01", "s02", "s11", "s12", "s2", "s22")), "ANY_TOP": any_of(("top_1", "top_2"))})
        return result

    @staticmethod
    def _split(data: pd.DataFrame) -> pd.Series:
        # Split every ETF chronologically, rather than mixing its newest bars
        # into another ETF's training set.
        n = len(data); labels = np.full(n, "LOCKBOX", dtype=object)
        labels[: int(n * .6)] = "EXPLORE"; labels[int(n * .6): int(n * .8)] = "SELECT"
        return pd.Series(labels, index=data.index)

    def _trade(self, data: pd.DataFrame, symbol: str, signal_index: int, spec: SignalRuleSpec, signals: dict[str, pd.Series]) -> dict | None:
        entry_index = signal_index + 1
        if entry_index >= len(data):
            return None
        last = min(entry_index + 5, len(data) - 1)
        exit_index, reason = entry_index + spec.holding_days, f"FIXED_{spec.holding_days}"
        if spec.exit_rule != "FIXED":
            exit_index, reason = last, "MAX_HOLD"
            required_s = signals.get(spec.exit_anchor or "ANY_S", pd.Series(False, index=data.index))
            top_ok = _recent(signals["ANY_TOP"], spec.delta_lookback or 0)
            delta_ok = _recent(data["delta_high"], spec.delta_lookback or 0)
            for i in range(entry_index, last + 1):
                if not bool(required_s.iloc[i]):
                    continue
                if spec.exit_rule == "FIRST_S" or (spec.exit_rule == "DELTA_HIGH_AND_S" and bool(delta_ok.iloc[i])) or (spec.exit_rule == "TOP_AND_S" and bool(top_ok.iloc[i])):
                    exit_index, reason = i + 1, spec.exit_rule
                    break
        if exit_index >= len(data):
            # The requested end date may not complete the position.  Preserve
            # it in the audit but never manufacture a future return.
            return {"symbol": symbol, "signal_date": data.date.iloc[signal_index].date().isoformat(), "entry_date": data.date.iloc[entry_index].date().isoformat(), "exit_date": None, "open": True, "rule_id": spec.id, "entry_anchor": spec.entry_anchor, "exit_reason": "OPEN", "split": self._split(data).iloc[signal_index]}
        cost = spec.cost_bps_per_side / 10_000
        entry, exit_ = float(data.open.iloc[entry_index]), float(data.open.iloc[exit_index])
        observed = data.iloc[entry_index:exit_index + 1]
        return {"symbol": symbol, "signal_date": data.date.iloc[signal_index].date().isoformat(), "entry_date": data.date.iloc[entry_index].date().isoformat(), "exit_date": data.date.iloc[exit_index].date().isoformat(), "open": False, "rule_id": spec.id, "entry_anchor": spec.entry_anchor, "exit_reason": reason, "split": self._split(data).iloc[signal_index], "holding_days": exit_index - entry_index, "gross_return": exit_ / entry - 1, "net_return": exit_ * (1 - cost) / (entry * (1 + cost)) - 1, "mfe": float(observed.high.max() / entry - 1), "mae": float(observed.low.min() / entry - 1)}

    def _trades(self, data: pd.DataFrame, symbol: str, spec: SignalRuleSpec, signals: dict[str, pd.Series], *, stateful: bool) -> list[dict]:
        anchor = _cluster(signals[spec.entry_anchor])
        if spec.delta_direction == "LOW":
            anchor &= _recent(data["delta_low"], int(spec.delta_lookback or 0))
        result: list[dict] = []; available = 0
        for i, hit in anchor.items():
            if not hit or (stateful and i < available):
                continue
            trade = self._trade(data, symbol, int(i), spec, signals)
            if trade is None:
                continue
            result.append(trade)
            if stateful and not trade["open"]:
                # Exit has priority and the next signal day is a cooldown day.
                available = int(i) + int(trade["holding_days"]) + 3
        return result

    def _metrics(self, trades: list[dict], *, seed: int = 0) -> dict:
        closed = [x for x in trades if not x.get("open")]
        if not closed:
            return {"signal_clusters": len(trades), "sample_count": 0, "average_net_return": None, "median_net_return": None, "win_rate": None, "average_mfe": None, "average_mae": None, "net_return_ci_95": [None, None]}
        values = np.array([x["net_return"] for x in closed], dtype=float)
        # Calendar/block bootstrap: groups are five trading-day signal blocks,
        # so correlated nearby signal clusters are resampled together.
        blocks: dict[str, list[float]] = {}
        for trade in closed:
            block = pd.Timestamp(trade["signal_date"]).to_period("W-FRI").start_time.isoformat()
            blocks.setdefault(block, []).append(float(trade["net_return"]))
        block_values = [np.asarray(v) for v in blocks.values()]
        rng = np.random.default_rng(self.random_seed + seed)
        samples = []
        for _ in range(self.bootstrap_samples):
            chosen = rng.integers(0, len(block_values), size=len(block_values))
            samples.append(float(np.concatenate([block_values[i] for i in chosen]).mean()))
        return {"signal_clusters": len(trades), "sample_count": len(closed), "average_net_return": float(values.mean()), "net_return_std": float(values.std(ddof=1)) if len(values) > 1 else 0.0, "median_net_return": float(np.median(values)), "win_rate": float((values > 0).mean()), "average_mfe": float(np.mean([x["mfe"] for x in closed])), "average_mae": float(np.mean([x["mae"] for x in closed])), "net_return_ci_95": [float(np.quantile(samples, .025)), float(np.quantile(samples, .975))]}

    @staticmethod
    def _status(metrics: dict, wf_positive_rate: float | None = None, cost_robust: bool = False, breadth: int = 0) -> str:
        n, mean = metrics["sample_count"], metrics["average_net_return"]
        if n < 30: return "证据不足"
        if mean is None or mean <= 0 or metrics["net_return_ci_95"][0] is None or metrics["net_return_ci_95"][0] <= 0: return "已拒绝"
        if n >= 100 and cost_robust and breadth >= 3 and (wf_positive_rate is None or wf_positive_rate >= .6): return "研究候选"
        return "证据不足"

    def _random_baseline(self, data_by_symbol: dict[str, pd.DataFrame], trades: list[dict], spec: SignalRuleSpec) -> list[dict]:
        rng = np.random.default_rng(self.random_seed + sum(ord(char) for char in spec.id) % 100_000)
        baseline = []
        for trade in trades:
            if trade.get("open"): continue
            data = data_by_symbol[trade["symbol"]]; hold = int(trade["holding_days"])
            candidates = np.arange(0, len(data) - hold - 2)
            if not len(candidates): continue
            i = int(rng.choice(candidates)); entry, exit_ = i + 1, i + 1 + hold; cost = spec.cost_bps_per_side / 10_000
            baseline.append({"symbol": trade["symbol"], "signal_date": data.date.iloc[i].date().isoformat(), "entry_date": data.date.iloc[entry].date().isoformat(), "exit_date": data.date.iloc[exit_].date().isoformat(), "split": trade["split"], "open": False, "net_return": float(data.open.iloc[exit_]) * (1-cost) / (float(data.open.iloc[entry]) * (1+cost)) - 1, "mfe": 0., "mae": 0.})
        return baseline

    def _walk_forward(self, candidates: list[tuple[SignalRuleSpec, dict[str, pd.DataFrame], dict[str, dict[str, pd.Series]]]]) -> dict:
        windows = []
        # A genuinely expanding train/test selection: freeze a single winner on
        # prior observations, then assess it over the next 63 sessions.
        if not candidates: return {"windows": windows, "positive_window_rate": None}
        common = sorted(set.intersection(*[set(frame.date.dt.normalize()) for _, frames, _ in candidates[:1] for frame in frames.values()]))
        for end in range(504, len(common) - 63 + 1, 21):
            train_end, test_dates = common[end - 5], set(common[end:end + 63])  # purge five bars
            scored = []
            for spec, frames, signal_sets in candidates:
                trades = [t for symbol, frame in frames.items() for t in self._trades(frame, symbol, spec, signal_sets[symbol], stateful=True) if not t.get("open") and pd.Timestamp(t["exit_date"]) <= train_end]
                metric = self._metrics(trades); scored.append((metric["average_net_return"] or -float("inf"), spec, frames, signal_sets))
            _, selected, frames, signal_sets = max(scored, key=lambda x: x[0])
            test = [t for symbol, frame in frames.items() for t in self._trades(frame, symbol, selected, signal_sets[symbol], stateful=True) if not t.get("open") and pd.Timestamp(t["signal_date"]) in test_dates]
            metrics = self._metrics(test, seed=end)
            windows.append({"train_end": train_end.date().isoformat(), "test_start": common[end].date().isoformat(), "test_end": common[end + 62].date().isoformat(), "selected_rule": selected.id, **metrics})
        active = [w for w in windows if w["sample_count"]]
        return {"windows": windows, "positive_window_rate": sum((w["average_net_return"] or 0) > 0 for w in active) / len(active) if active else None}

    @staticmethod
    def _equal_weight_portfolio(trades: list[dict]) -> tuple[float, float]:
        """Buy-and-hold equal allocation per ETF; no cross-symbol leverage."""
        by_symbol: dict[str, list[dict]] = {}
        for trade in trades:
            by_symbol.setdefault(trade["symbol"], []).append(trade)
        if not by_symbol:
            return 0.0, 0.0
        terminal, drawdowns = [], []
        for rows in by_symbol.values():
            curve = np.cumprod([1 + float(x["net_return"]) for x in rows])
            terminal.append(float(curve[-1] - 1))
            drawdowns.append(float((curve / np.maximum.accumulate(curve) - 1).min()))
        return float(np.mean(terminal)), float(np.mean(drawdowns))

    def run(self, bars_by_symbol: dict[str, pd.DataFrame], *, data_provenance: dict | None = None) -> dict:
        if not bars_by_symbol: raise ValueError("at least one ETF dataset is required")
        provenance = data_provenance or {"source": "local_csv", "datasets": {s.upper(): dataframe_identity(b) for s, b in bars_by_symbol.items()}}
        snapshot_hash = provenance_sha256(provenance)
        features: dict[str, dict[str, pd.DataFrame]] = {"1.0": {}, "2.0": {}}
        signals: dict[str, dict[str, dict[str, pd.Series]]] = {"1.0": {}, "2.0": {}}
        delta_audit: dict[str, dict] = {}
        for symbol, bars in bars_by_symbol.items():
            if len(bars) < 30: raise ValueError(f"{symbol}: at least 30 daily bars are required")
            for version in ("1.0", "2.0"):
                frame, forecasts = self._features(bars, version)
                features[version][symbol.upper()] = frame; signals[version][symbol.upper()] = self._signal_map(frame, version)
                if version == "1.0": delta_audit[symbol.upper()] = {"forecast_count": len(forecasts), "semantic": "published before signal-day close; signal day inside forecast window"}
        ledger: list[dict] = []; phase1: list[dict] = []; survivors: list[SignalRuleSpec] = []
        for version, anchors in (("1.0", V1_ENTRIES), ("2.0", V2_ENTRIES)):
            for anchor in anchors:
                for horizon in HORIZONS:
                    for cost in COST_SCENARIOS:
                        spec = SignalRuleSpec(version, anchor, holding_days=horizon, cost_bps_per_side=cost, data_snapshot_hash=snapshot_hash)
                        all_trades = [t for sym, frame in features[version].items() for t in self._trades(frame, sym, spec, signals[version][sym], stateful=False)]
                        baseline = self._random_baseline(features[version], all_trades, spec)
                        for split in ("EXPLORE", "SELECT", "LOCKBOX"):
                            actual = [t for t in all_trades if t["split"] == split]; metrics = self._metrics(actual, seed=len(ledger)); random_metrics = self._metrics([t for t in baseline if t["split"] == split], seed=len(ledger)+1)
                            row = {"phase": "single_signal", "rule": asdict(spec), "rule_id": spec.id, "split": split, "metrics": metrics, "random_baseline": random_metrics, "edge_vs_random": None if metrics["average_net_return"] is None or random_metrics["average_net_return"] is None else metrics["average_net_return"] - random_metrics["average_net_return"]}
                            phase1.append(row); ledger.append(row)
                        explore = phase1[-3]
                        if cost == 10 and explore["metrics"]["sample_count"] >= 5 and (explore["metrics"]["average_net_return"] or 0) > 0: survivors.append(spec)
        # Delta adds information only after an exploratory primary signal passes.
        delta_rows: list[dict] = []
        for primary in survivors:
            for lookback in LOOKBACKS:
                spec = SignalRuleSpec(primary.indicator_version, primary.entry_anchor, "LOW", lookback, holding_days=primary.holding_days, cost_bps_per_side=primary.cost_bps_per_side, data_snapshot_hash=snapshot_hash)
                combined = [t for sym, frame in features[spec.indicator_version].items() for t in self._trades(frame, sym, spec, signals[spec.indicator_version][sym], stateful=False)]
                standalone = [t for sym, frame in features[primary.indicator_version].items() for t in self._trades(frame, sym, primary, signals[primary.indicator_version][sym], stateful=False)]
                for split in ("EXPLORE", "SELECT", "LOCKBOX"):
                    cm, pm = self._metrics([t for t in combined if t["split"] == split], seed=len(ledger)), self._metrics([t for t in standalone if t["split"] == split], seed=len(ledger)+1)
                    row = {"phase": "delta_incremental", "rule": asdict(spec), "rule_id": spec.id, "primary_rule_id": primary.id, "split": split, "metrics": cm, "primary_metrics": pm, "incremental_net_return": None if cm["average_net_return"] is None or pm["average_net_return"] is None else cm["average_net_return"] - pm["average_net_return"]}
                    delta_rows.append(row); ledger.append(row)
        # Replay only selection survivors.  It models actual long positions;
        # new B markers while long are recorded implicitly but never pyramid.
        replay_rows: list[dict] = []; replay_candidates = []
        # The middle chronological segment selects which DELTA combinations
        # receive a lockbox exit study.  Capping the pre-registered review set
        # keeps a synchronous research request tractable while recording every
        # rejected/omitted phase-one and phase-two trial in the ledger.
        selected_delta = [row for row in delta_rows if row["split"] == "SELECT" and (row["incremental_net_return"] or 0) > 0]
        selected_delta.sort(key=lambda row: (-(row["incremental_net_return"] or 0), row["rule_id"]))
        for delta in selected_delta[:12]:
            base_spec = SignalRuleSpec(**delta["rule"])
            s_anchors = (("ANY_S", "S1", "S2") if base_spec.indicator_version == "1.0" else ("ANY_S", "S01", "S02", "S11", "S12", "S2", "S22"))
            exit_variants = [("FIXED", None, 0)]
            exit_variants += [("FIRST_S", anchor, 0) for anchor in s_anchors]
            exit_variants += [("DELTA_HIGH_AND_S", "ANY_S", lookback) for lookback in LOOKBACKS]
            exit_variants += [("TOP_AND_S", "ANY_S", lookback) for lookback in LOOKBACKS]
            for cost in COST_SCENARIOS:
                spec = SignalRuleSpec(base_spec.indicator_version, base_spec.entry_anchor, "LOW", base_spec.delta_lookback, holding_days=base_spec.holding_days, cost_bps_per_side=cost, data_snapshot_hash=snapshot_hash)
                s_anchors = (("ANY_S", "S1", "S2") if spec.indicator_version == "1.0" else ("ANY_S", "S01", "S02", "S11", "S12", "S2", "S22"))
                for exit_rule, exit_anchor, lookback in exit_variants:
                    replay = SignalRuleSpec(spec.indicator_version, spec.entry_anchor, "LOW", spec.delta_lookback, exit_rule, exit_anchor, spec.holding_days, spec.cost_bps_per_side, data_snapshot_hash=snapshot_hash)
                    trades = [t for sym, frame in features[replay.indicator_version].items() for t in self._trades(frame, sym, replay, signals[replay.indicator_version][sym], stateful=True)]
                    replay_candidates.append((replay, features[replay.indicator_version], signals[replay.indicator_version]))
                    for split in ("EXPLORE", "SELECT", "LOCKBOX"):
                        closed = [t for t in trades if t["split"] == split and not t.get("open")]; m = self._metrics(closed, seed=len(ledger))
                        equity, dd = self._equal_weight_portfolio(closed)
                        row = {"phase": "portfolio_replay", "rule": asdict(replay), "rule_id": replay.id, "split": split, "metrics": m, "equity_return": equity, "max_drawdown": dd, "turnover": len(closed), "portfolio_construction": "equal weight across ETFs; positions never overlap within an ETF", "trades": closed[-100:]}
                        replay_rows.append(row); ledger.append(row)
        wf_ranked = [row for row in replay_rows if row["split"] == "SELECT" and row["rule"]["cost_bps_per_side"] == 10]
        wf_ranked.sort(key=lambda row: (-(row["metrics"]["average_net_return"] or -float("inf")), row["rule_id"]))
        wf_ids = {row["rule_id"] for row in wf_ranked[:12]}
        # Walk-forward is a final robustness check over the selection-set
        # finalists, not another exhaustive parameter search.
        wf = self._walk_forward([candidate for candidate in replay_candidates if candidate[0].id in wf_ids])
        # FDR ledger is deliberately complete, including losers/gated trials.
        pvals = []
        for ledger_index, row in enumerate(ledger):
            m = row["metrics"]; n = m["sample_count"]
            if n > 1 and m["average_net_return"] is not None:
                standard_error = m.get("net_return_std", 0.0) / math.sqrt(n)
                pvals.append((ledger_index, _normal_pvalue(m["average_net_return"] / max(1e-12, standard_error))))
        fdr = {i: min(1., p * max(1, len(pvals)) / rank) for rank, (i, p) in enumerate(sorted(pvals, key=lambda x: x[1]), start=1)}
        for i, row in enumerate(ledger): row["fdr_q_value"] = fdr.get(i)
        lockbox = [row for row in replay_rows if row["split"] == "LOCKBOX"]
        for row in lockbox:
            per_symbol = {s: self._metrics([t for t in row["trades"] if t["symbol"] == s]) for s in features[row["rule"]["indicator_version"]]}
            shape = {key: value for key, value in row["rule"].items() if key != "cost_bps_per_side"}
            robust_costs = all(any(x["split"] == "LOCKBOX" and {key: value for key, value in x["rule"].items() if key != "cost_bps_per_side"} == shape and x["rule"]["cost_bps_per_side"] == cost and (x["metrics"]["average_net_return"] or 0) > 0 for x in replay_rows) for cost in (10, 20))
            row["research_status"] = self._status(row["metrics"], wf.get("positive_window_rate"), robust_costs, sum(m["sample_count"] > 0 for m in per_symbol.values()))
        metadata = research_run_metadata(parameters={"protocol_id": PROTOCOL_ID, "symbols": sorted(s.upper() for s in bars_by_symbol), "horizons": HORIZONS, "cost_scenarios_bps_per_side": COST_SCENARIOS, "lookbacks": LOOKBACKS, "random_seed": self.random_seed}, data_provenance=provenance, stable_context={"execution": "T close confirmed -> T+1 open fill", "formula": "display booleans only"})
        return {"protocol_id": PROTOCOL_ID, "run_metadata": metadata, "signal_protocol": {"execution": "T 日收盘确认，T+1 开盘成交", "delta": "仅历史发布且当日仍处于预测窗口的 DELTA_LOW/HIGH", "position": "仅做多；退出仅平现有多头；同标的不加仓；平仓后冷却 1 个交易日", "gpma2_notice": "本地等价公式研究结果；富途逐 Bar 对账完成前不可作为权威实盘认证"}, "delta_audit": delta_audit, "single_signal": phase1, "delta_incremental": delta_rows, "portfolio_replays": replay_rows, "walk_forward": wf, "lockbox": lockbox, "trial_ledger": ledger, "assessment_labels": {"研究候选": "满足当前锁箱、成本、样本量与稳健性门槛", "证据不足": "样本或稳健性门槛不足，不能形成交易指令", "已拒绝": "当前锁箱或置信区间未显示净优势"}}
