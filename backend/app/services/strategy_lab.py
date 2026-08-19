"""Causal DELTA × GPMAPRO strategy research.

The service deliberately separates DELTA's retrospective structure points from
the forecasts that were actually available at each historical close.  Strategy
signals are generated at the close and always execute at the following open.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmapro_engine import GpmaProEngine


ENTRY_RULES = {
    "B_ONLY": "B 直接买入",
    "DELTA_LOW_THEN_B": "DELTA LOW 窗口内出现 B",
    "BOTTOM_THEN_B": "底部背离后出现 B",
    "DELTA_BOTTOM_B": "DELTA LOW + 底部背离 + B",
}
EXIT_RULES = {
    "FIXED_5": "固定持有 5 日",
    "FIXED_10": "固定持有 10 日",
    "FIXED_20": "固定持有 20 日",
    "FIRST_S": "首个 S 退出",
    "DELTA_HIGH_AND_S": "DELTA HIGH 窗口内出现 S",
    "TOP_AND_S": "顶部背离后出现 S",
}
FORMULA_VERSION = "GPMAPRO_JUSTIN_WEAPON + AI_ITD_CAUSAL_V1"


@dataclass(frozen=True)
class StrategyLabConfig:
    confirmation_bars: int = 5
    max_hold_bars: int = 60
    cost_bps_per_side: float = 10.0
    bootstrap_samples: int = 500
    random_seed: int = 20260817
    min_history_bars: int = 252
    walk_forward_test_bars: int = 63
    walk_forward_step_bars: int = 63


def _as_date(value: object) -> date:
    return pd.Timestamp(value).date()


def _finite(value: float | np.floating | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


class StrategyLabService:
    """Pre-registered long-only entry/exit combinations with audit records."""

    def __init__(self, config: StrategyLabConfig | None = None):
        self.config = config or StrategyLabConfig()
        self.gpma = GpmaProEngine()

    def _delta_forecasts(self, data: pd.DataFrame, progress=None) -> list[dict]:
        """Replay the model at every historical close and freeze each forecast."""
        records: list[dict] = []
        dates = pd.to_datetime(data.date).dt.date.tolist()
        engine = ITDDeltaEngine()
        # Start only after one full calendar skeleton is available.  The engine
        # itself makes the final history sufficiency decision.
        for index in range(1, len(data)):
            prefix = data.iloc[: index + 1].copy()
            analysis = engine.analyze(prefix)
            prediction = analysis.get("next_prediction")
            if not prediction:
                continue
            published = dates[index]
            start, end = date.fromisoformat(prediction["window_start"]), date.fromisoformat(prediction["window_end"])
            # A prediction that is already over cannot be used at this close.
            if end < published:
                continue
            records.append({
                "forecast_id": f"{published.isoformat()}:{prediction['id']}",
                "published_at": published.isoformat(),
                "event_type": prediction["type"],
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "expected_date": prediction["expected_date"],
                "confidence": float(prediction["confidence"]),
            })
            if progress and (index % 25 == 0 or index == len(data) - 1):
                progress(index + 1, len(data))
        if progress:
            progress(len(data), len(data))
        return records

    @staticmethod
    def _active_delta_flags(dates: list[date], forecasts: list[dict]) -> tuple[pd.Series, pd.Series]:
        low = pd.Series(False, index=range(len(dates)))
        high = pd.Series(False, index=range(len(dates)))
        for item in forecasts:
            published = date.fromisoformat(item["published_at"])
            start, end = date.fromisoformat(item["window_start"]), date.fromisoformat(item["window_end"])
            target = low if item["event_type"] == "LOW" else high
            for index, current in enumerate(dates):
                # The forecast must have existed before the signal-day close.
                if published < current and start <= current <= end:
                    target.iloc[index] = True
        return low, high

    def _features(self, bars: pd.DataFrame, *, forecast_key: str | None = None, forecast_cache=None, progress=None) -> tuple[pd.DataFrame, list[dict]]:
        data = self.gpma.calculate(bars).copy().reset_index(drop=True)
        data["date"] = pd.to_datetime(data.date)
        forecasts = forecast_cache.get(forecast_key) if forecast_cache and forecast_key else None
        if forecasts is None:
            forecasts = self._delta_forecasts(data, progress=progress)
            if forecast_cache and forecast_key:
                forecast_cache.put(forecast_key, forecasts)
        dates = [_as_date(value) for value in data.date]
        delta_low, delta_high = self._active_delta_flags(dates, forecasts)
        data["delta_low_window"] = delta_low
        data["delta_high_window"] = delta_high
        data["b_signal"] = data[["b1", "b2", "b3"]].any(axis=1)
        data["s_signal"] = data[["s1", "s2"]].any(axis=1)
        data["bottom_divergence"] = data[["bottom_face", "bottom_2", "bottom_3"]].any(axis=1)
        data["top_divergence"] = data[["top_face", "top_2", "top_3"]].any(axis=1)
        return data, forecasts

    def _entry_flags(self, data: pd.DataFrame) -> dict[str, pd.Series]:
        recent_bottom = data["bottom_divergence"].astype(int).rolling(self.config.confirmation_bars + 1, min_periods=1).max().astype(bool)
        b = data["b_signal"]
        return {
            "B_ONLY": b,
            "DELTA_LOW_THEN_B": data["delta_low_window"] & b,
            "BOTTOM_THEN_B": recent_bottom & b,
            "DELTA_BOTTOM_B": data["delta_low_window"] & recent_bottom & b,
        }

    def _exit_index(self, data: pd.DataFrame, entry_index: int, exit_rule: str) -> tuple[int, str] | None:
        entry_execution = entry_index + 1
        fixed = int(exit_rule.split("_")[1]) if exit_rule.startswith("FIXED_") else None
        if fixed is not None:
            target = entry_execution + fixed
            return (target, exit_rule) if target < len(data) else None
        latest = min(entry_execution + self.config.max_hold_bars, len(data) - 1)
        recent_top = data["top_divergence"].astype(int).rolling(self.config.confirmation_bars + 1, min_periods=1).max().astype(bool)
        for signal_index in range(entry_execution, latest):
            if not bool(data["s_signal"].iloc[signal_index]):
                continue
            if exit_rule == "FIRST_S":
                return signal_index + 1, "S"
            if exit_rule == "DELTA_HIGH_AND_S" and bool(data["delta_high_window"].iloc[signal_index]):
                return signal_index + 1, "DELTA_HIGH + S"
            if exit_rule == "TOP_AND_S" and bool(recent_top.iloc[signal_index]):
                return signal_index + 1, "TOP + S"
        target = entry_execution + self.config.max_hold_bars
        return (target, "MAX_HOLD") if target < len(data) else None

    def _trade(self, data: pd.DataFrame, symbol: str, entry_signal_index: int, entry_rule: str, exit_rule: str) -> dict | None:
        entry_index = entry_signal_index + 1
        if entry_index >= len(data):
            return None
        exit_plan = self._exit_index(data, entry_signal_index, exit_rule)
        if exit_plan is None:
            return None
        exit_index, exit_reason = exit_plan
        if exit_index <= entry_index:
            return None
        cost = self.config.cost_bps_per_side / 10_000
        entry, exit_ = float(data.open.iloc[entry_index]), float(data.open.iloc[exit_index])
        gross = exit_ / entry - 1
        net = exit_ * (1 - cost) / (entry * (1 + cost)) - 1
        observed = data.iloc[entry_index: exit_index + 1]
        return {
            "symbol": symbol.upper(), "entry_rule": entry_rule, "exit_rule": exit_rule,
            "signal_date": data.date.iloc[entry_signal_index].date().isoformat(),
            "entry_date": data.date.iloc[entry_index].date().isoformat(),
            "exit_date": data.date.iloc[exit_index].date().isoformat(),
            "entry_price": entry, "exit_price": exit_, "gross_return": gross, "net_return": net,
            "mfe": float(observed.high.max() / entry - 1), "mae": float(observed.low.min() / entry - 1),
            "holding_bars": exit_index - entry_index, "exit_reason": exit_reason,
            "delta_low_active": bool(data.delta_low_window.iloc[entry_signal_index]),
            "bottom_divergence": bool(data.bottom_divergence.iloc[entry_signal_index]),
        }

    def _strategy_trades(self, data: pd.DataFrame, symbol: str, entry_rule: str, exit_rule: str) -> list[dict]:
        entries = self._entry_flags(data)[entry_rule]
        result: list[dict] = []
        next_available = 0
        for index, active in entries.items():
            if not active or index < next_available:
                continue
            trade = self._trade(data, symbol, int(index), entry_rule, exit_rule)
            if trade:
                result.append(trade)
                next_available = int(data.index[data.date == pd.Timestamp(trade["exit_date"])][0]) + 1
        return result

    def _metrics(self, trades: list[dict], *, seed_offset: int = 0) -> dict:
        if not trades:
            return {"sample_count": 0, "average_gross_return": None, "average_net_return": None, "median_net_return": None, "positive_rate": None, "average_mfe": None, "average_mae": None, "net_return_ci_95": [None, None]}
        values = lambda field: [float(item[field]) for item in trades]
        net = np.asarray(values("net_return")); rng = np.random.default_rng(self.config.random_seed + seed_offset)
        means = rng.choice(net, size=(self.config.bootstrap_samples, len(net)), replace=True).mean(axis=1)
        return {
            "sample_count": len(trades), "average_gross_return": statistics.mean(values("gross_return")),
            "average_net_return": statistics.mean(values("net_return")), "median_net_return": statistics.median(values("net_return")),
            "positive_rate": sum(value > 0 for value in values("net_return")) / len(trades),
            "average_mfe": statistics.mean(values("mfe")), "average_mae": statistics.mean(values("mae")),
            "net_return_ci_95": [float(np.quantile(means, .025)), float(np.quantile(means, .975))],
        }

    def _random_baseline(self, data: pd.DataFrame, symbol: str, trades: list[dict], entry_rule: str, exit_rule: str) -> list[dict]:
        rng = np.random.default_rng(self.config.random_seed + sum(map(ord, f"{symbol}:{entry_rule}:{exit_rule}")))
        result: list[dict] = []
        for trade in trades:
            hold = int(trade["holding_bars"])
            candidates = np.arange(0, max(0, len(data) - hold - 1))
            if not len(candidates):
                continue
            signal_index = int(rng.choice(candidates))
            entry_index, exit_index = signal_index + 1, signal_index + 1 + hold
            entry, exit_ = float(data.open.iloc[entry_index]), float(data.open.iloc[exit_index])
            cost = self.config.cost_bps_per_side / 10_000
            observed = data.iloc[entry_index: exit_index + 1]
            result.append({"symbol": symbol.upper(), "entry_rule": entry_rule, "exit_rule": exit_rule, "signal_date": data.date.iloc[signal_index].date().isoformat(), "entry_date": data.date.iloc[entry_index].date().isoformat(), "exit_date": data.date.iloc[exit_index].date().isoformat(), "entry_price": entry, "exit_price": exit_, "gross_return": exit_ / entry - 1, "net_return": exit_ * (1 - cost) / (entry * (1 + cost)) - 1, "mfe": float(observed.high.max() / entry - 1), "mae": float(observed.low.min() / entry - 1), "holding_bars": hold, "exit_reason": "MATCHED_RANDOM"})
        return result

    def _delta_audit(self, data: pd.DataFrame, forecasts: list[dict]) -> dict:
        completed: list[dict] = []
        dates = [_as_date(value) for value in data.date]
        for item in forecasts:
            end = date.fromisoformat(item["window_end"])
            positions = [index for index, value in enumerate(dates) if value >= end]
            if not positions:
                continue
            start = date.fromisoformat(item["window_start"])
            start_positions = [index for index, value in enumerate(dates) if value >= start]
            if not start_positions:
                continue
            start_index, end_index = start_positions[0], positions[0]
            horizon = min(len(data) - 1, end_index + 10)
            if horizon <= start_index:
                continue
            direction = 1 if item["event_type"] == "LOW" else -1
            result = direction * (float(data.close.iloc[horizon]) / float(data.close.iloc[start_index]) - 1)
            completed.append({**item, "evaluated_at": dates[horizon].isoformat(), "window_return_10": result, "positive": result > 0})
        values = [float(item["window_return_10"]) for item in completed]
        return {"forecast_count": len(forecasts), "completed_count": len(completed), "positive_rate": sum(value > 0 for value in values) / len(values) if values else None, "average_window_return_10": statistics.mean(values) if values else None, "records": completed[-100:]}

    def _walk_forward(self, data_by_symbol: dict[str, pd.DataFrame], all_trades: dict[str, list[dict]]) -> dict:
        common = sorted(set.intersection(*[set(pd.to_datetime(data.date)) for data in data_by_symbol.values()]))
        per_strategy: dict[str, dict] = {}
        for entry in ENTRY_RULES:
            for exit_ in EXIT_RULES:
                key = f"{entry}__{exit_}"; windows = []
                for start in range(self.config.min_history_bars, len(common) - self.config.walk_forward_test_bars + 1, self.config.walk_forward_step_bars):
                    test_dates = common[start: start + self.config.walk_forward_test_bars]
                    selected = [trade for trades in all_trades.values() for trade in trades if trade["entry_rule"] == entry and trade["exit_rule"] == exit_ and pd.Timestamp(trade["entry_date"]) in set(test_dates)]
                    metrics = self._metrics(selected, seed_offset=start)
                    windows.append({"test_start": test_dates[0].date().isoformat(), "test_end": test_dates[-1].date().isoformat(), **metrics})
                active = [item for item in windows if item["sample_count"]]
                positive = [item for item in active if (item["average_net_return"] or 0) > 0]
                per_strategy[key] = {"windows": windows, "summary": {"window_count": len(windows), "active_window_count": len(active), "positive_window_rate": len(positive) / len(active) if active else None, "average_test_return": statistics.mean(item["average_net_return"] for item in active) if active else None, "verdict": "INSUFFICIENT" if len(active) < 4 else "PROMISING" if len(positive) / len(active) >= .6 and statistics.mean(item["average_net_return"] for item in active) > 0 else "NOT_ROBUST"}}
        return per_strategy

    def run(self, bars_by_symbol: dict[str, pd.DataFrame], *, data_provenance: dict | None = None, forecast_cache=None, forecast_keys: dict[str, str] | None = None, progress=None) -> dict:
        features: dict[str, pd.DataFrame] = {}; audits: dict[str, dict] = {}; all_trades: dict[str, list[dict]] = {}; random_trades: dict[str, list[dict]] = {}
        total_symbols = len(bars_by_symbol)
        for ordinal, (symbol, bars) in enumerate(bars_by_symbol.items(), start=1):
            def report(done: int, total: int, *, _symbol=symbol, _ordinal=ordinal):
                if progress:
                    progress({"stage": "delta_replay", "symbol": _symbol, "completed_symbols": _ordinal - 1, "total_symbols": total_symbols, "symbol_progress": done / total, "progress": ((_ordinal - 1) + done / total) / total_symbols})
            data, forecasts = self._features(bars, forecast_key=(forecast_keys or {}).get(symbol.upper()), forecast_cache=forecast_cache, progress=report)
            features[symbol.upper()] = data; audits[symbol.upper()] = self._delta_audit(data, forecasts)
            all_trades[symbol.upper()] = []
            random_trades[symbol.upper()] = []
            for entry in ENTRY_RULES:
                for exit_ in EXIT_RULES:
                    trades = self._strategy_trades(data, symbol, entry, exit_)
                    all_trades[symbol.upper()].extend(trades)
                    random_trades[symbol.upper()].extend(self._random_baseline(data, symbol, trades, entry, exit_))
            if progress:
                progress({"stage": "strategy_matrix", "symbol": symbol, "completed_symbols": ordinal, "total_symbols": total_symbols, "symbol_progress": 1.0, "progress": ordinal / total_symbols})
        strategies = []
        for entry, entry_label in ENTRY_RULES.items():
            for exit_, exit_label in EXIT_RULES.items():
                key = f"{entry}__{exit_}"
                actual = [trade for trades in all_trades.values() for trade in trades if trade["entry_rule"] == entry and trade["exit_rule"] == exit_]
                baseline = [trade for trades in random_trades.values() for trade in trades if trade["entry_rule"] == entry and trade["exit_rule"] == exit_]
                metrics, random_metrics = self._metrics(actual, seed_offset=len(strategies)), self._metrics(baseline, seed_offset=10_000 + len(strategies))
                per_symbol = {}
                for symbol, symbol_trades in all_trades.items():
                    selected = [trade for trade in symbol_trades if trade["entry_rule"] == entry and trade["exit_rule"] == exit_]
                    selected_metrics = self._metrics(selected, seed_offset=len(strategies) + sum(map(ord, symbol)))
                    per_symbol[symbol] = {**selected_metrics, "net_return_sum": float(sum(float(trade["net_return"]) for trade in selected))}
                b_trades = [trade for trades in all_trades.values() for trade in trades if trade["entry_rule"] == "B_ONLY" and trade["exit_rule"] == exit_]
                b_metrics = self._metrics(b_trades, seed_offset=20_000 + len(strategies))
                strategies.append({"id": key, "entry_rule": entry, "entry_label": entry_label, "exit_rule": exit_, "exit_label": exit_label, "metrics": metrics, "random_baseline": random_metrics, "b_only_baseline": b_metrics, "per_symbol": per_symbol, "net_edge_vs_random": None if metrics["average_net_return"] is None or random_metrics["average_net_return"] is None else metrics["average_net_return"] - random_metrics["average_net_return"], "trades": actual[:200]})
        metadata = {"formula": FORMULA_VERSION, "execution": "signal-day close; next-trading-day open", "cost_bps_per_side": self.config.cost_bps_per_side, "confirmation_bars": self.config.confirmation_bars, "max_hold_bars": self.config.max_hold_bars, "entry_rules": ENTRY_RULES, "exit_rules": EXIT_RULES, "data_provenance": data_provenance or {"source": "local_csv"}}
        fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        walk_forward = self._walk_forward(features, all_trades)
        for strategy in strategies:
            walk = walk_forward[strategy["id"]]["summary"]
            positive_contributions = [max(0.0, item["net_return_sum"]) for item in strategy["per_symbol"].values()]
            total_positive = sum(positive_contributions)
            dominant_share = max(positive_contributions, default=0.0) / total_positive if total_positive else None
            active_symbols = sum(item["sample_count"] > 0 for item in strategy["per_symbol"].values())
            checks = {
                "beats_random_after_cost": strategy["net_edge_vs_random"] is not None and strategy["net_edge_vs_random"] > 0,
                "beats_b_only": strategy["metrics"]["average_net_return"] is not None and strategy["b_only_baseline"]["average_net_return"] is not None and strategy["metrics"]["average_net_return"] > strategy["b_only_baseline"]["average_net_return"],
                "oos_stable": walk["active_window_count"] >= 4 and (walk["positive_window_rate"] or 0) >= .6,
                "cross_asset_breadth": active_symbols >= 5,
                "not_single_etf_driven": dominant_share is not None and dominant_share <= .5,
                "ci_positive": strategy["metrics"]["net_return_ci_95"][0] is not None and strategy["metrics"]["net_return_ci_95"][0] > 0,
            }
            failed = [name for name, passed in checks.items() if not passed]
            strategy["research_assessment"] = {"label": "WORTH_CONTINUING" if not failed else ("NOT_ROBUST" if walk["active_window_count"] >= 4 else "INSUFFICIENT_EVIDENCE"), "checks": checks, "failed_checks": failed, "active_symbols": active_symbols, "dominant_etf_share": dominant_share}
        if progress:
            progress({"stage": "complete", "symbol": None, "completed_symbols": total_symbols, "total_symbols": total_symbols, "symbol_progress": 1.0, "progress": 1.0})
        return {"run_metadata": {**metadata, "fingerprint": fingerprint}, "delta_audit": audits, "strategies": strategies, "walk_forward": walk_forward, "assumptions": {"scope": "long-only research", "delta": "only forecasts published before the signal-day close activate a DELTA window", "divergence": "smile/arrow markers are confirmation conditions, not standalone orders", "execution": "all entries and exits execute at the following session open", "warning": "results are historical research evidence; current universes may have survivorship bias"}}
