"""Causal event-study backtest for DELTA, GPMAPRO and their combinations.

This is deliberately an event-return study, not a portfolio optimiser: each
signal is evaluated independently at the close where it becomes knowable.
"""
from __future__ import annotations

import statistics
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmapro_engine import GpmaProEngine


@dataclass(frozen=True)
class SignalBacktestConfig:
    horizons: tuple[int, ...] = (5, 10, 20)
    default_cost_bps: float = 10.0
    delta_confirmation_window: int = 5
    random_seed: int = 20260813
    bootstrap_samples: int = 1_000


class SignalBacktestService:
    def __init__(self, config: SignalBacktestConfig = SignalBacktestConfig()):
        self.config, self.gpma = config, GpmaProEngine()

    def _delta_flags(self, data: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict[int, dict]]:
        low = pd.Series(False, index=data.index); high = pd.Series(False, index=data.index)
        context: dict[int, dict] = {}
        # Recompute from each point-in-time prefix.  A bar is flagged only
        # when a window predicted from information available by that bar is
        # active; no later OHLC extremes can enter the backtest.
        engine = ITDDeltaEngine()
        for index in range(len(data)):
            known = data.iloc[:index + 1]
            if len(known) < 118:
                continue
            current = known.date.iloc[-1].date()
            for event in engine.signal_windows(known):
                if event["window_start"] <= current.isoformat() <= event["window_end"]:
                    (low if event["event_type"] == "LOW" else high).iloc[index] = True
                    context[index] = {"actual_date": event["anchor_date"], "confirmed_on": current.isoformat(), "tradable_on": data.date.iloc[index + 1].date().isoformat() if index + 1 < len(data) else None, "forecast_window": [event["window_start"], event["window_end"]]}
        return low, high, context

    def _signals(self, bars: pd.DataFrame) -> pd.DataFrame:
        data = self.gpma.calculate(bars).copy().reset_index(drop=True)
        delta_low, delta_high, delta_context = self._delta_flags(data)
        window = self.config.delta_confirmation_window
        low_window = delta_low.rolling(window, min_periods=1).max().astype(bool)
        high_window = delta_high.rolling(window, min_periods=1).max().astype(bool)
        result = pd.DataFrame({
            "DELTA_LOW": delta_low, "DELTA_HIGH": delta_high,
            "GPMAPRO_B": data[["b1", "b2", "b3"]].any(axis=1),
            "GPMAPRO_S": data[["s1", "s2"]].any(axis=1),
            "DELTA_LOW_X_B": low_window & data[["b1", "b2", "b3"]].any(axis=1),
            "DELTA_HIGH_X_S": high_window & data[["s1", "s2"]].any(axis=1),
        })
        result.attrs["delta_context"] = delta_context
        return result

    @staticmethod
    def _side(name: str) -> int:
        return -1 if name in {"DELTA_HIGH", "GPMAPRO_S", "DELTA_HIGH_X_S"} else 1

    def _trade(self, data: pd.DataFrame, index: int, signal: str, horizon: int, cost_bps: float, delta_context: dict | None = None) -> dict | None:
        if index + horizon + 1 >= len(data):
            return None
        entry_index, exit_index = index + 1, index + horizon + 1
        if exit_index >= len(data):
            return None
        entry, exit_ = float(data.open.iloc[entry_index]), float(data.open.iloc[exit_index])
        side = self._side(signal); future = data.iloc[entry_index:exit_index + 1]
        gross = side * (exit_ / entry - 1); mfe = side * ((float(future.high.max()) / entry - 1) if side > 0 else (float(future.low.min()) / entry - 1)); mae = side * ((float(future.low.min()) / entry - 1) if side > 0 else (float(future.high.max()) / entry - 1))
        net = gross - 2 * cost_bps / 10_000
        return {"date": data.date.iloc[index].date().isoformat(), "actual_date": (delta_context or {}).get("actual_date"), "signal_known_at": data.date.iloc[index].date().isoformat(), "entry_date": data.date.iloc[entry_index].date().isoformat(), "exit_date": data.date.iloc[exit_index].date().isoformat(), "signal": signal, "side": "LONG" if side > 0 else "SHORT", "horizon": horizon, "entry_price": entry, "exit_price": exit_, "gross_return": gross, "net_return": net, "mfe": mfe, "mae": mae}

    @staticmethod
    def _stats(trades: list[dict]) -> dict:
        if not trades:
            return {"sample_count": 0, "average_gross_return": None, "median_gross_return": None, "average_net_return": None, "median_net_return": None, "positive_rate": None, "average_mfe": None, "average_mae": None, "net_return_ci_95": [None, None]}
        values = lambda key: [float(x[key]) for x in trades]
        net = np.asarray(values("net_return")); rng = np.random.default_rng(20260813 + len(net))
        means = rng.choice(net, size=(min(1_000, max(200, len(net) * 20)), len(net)), replace=True).mean(axis=1)
        return {"sample_count": len(trades), "average_gross_return": statistics.mean(values("gross_return")), "median_gross_return": statistics.median(values("gross_return")), "average_net_return": statistics.mean(values("net_return")), "median_net_return": statistics.median(values("net_return")), "positive_rate": sum(x > 0 for x in values("net_return")) / len(trades), "average_mfe": statistics.mean(values("mfe")), "average_mae": statistics.mean(values("mae")), "net_return_ci_95": [float(np.quantile(means, .025)), float(np.quantile(means, .975))]}

    @staticmethod
    def _equal_weight_stats(stats: list[dict]) -> dict:
        available = [item for item in stats if item["sample_count"]]
        if not available:
            return SignalBacktestService._stats([])
        result = {"sample_count": sum(item["sample_count"] for item in available), "eligible_symbols": len(available), "aggregation": "EQUAL_WEIGHT_BY_SYMBOL"}
        for key in ("average_gross_return", "median_gross_return", "average_net_return", "median_net_return", "positive_rate", "average_mfe", "average_mae"):
            values = [float(item[key]) for item in available if item[key] is not None]
            result[key] = statistics.mean(values) if values else None
        ci = [item["net_return_ci_95"] for item in available if item["net_return_ci_95"][0] is not None]
        result["net_return_ci_95"] = [statistics.mean(item[0] for item in ci), statistics.mean(item[1] for item in ci)] if ci else [None, None]
        return result

    def run_symbol(self, bars: pd.DataFrame, symbol: str, *, horizons: tuple[int, ...] | None = None, cost_bps: float | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
        data = bars.copy().sort_values("date").reset_index(drop=True); data["date"] = pd.to_datetime(data.date)
        flags = self._signals(data); delta_context = flags.attrs.get("delta_context", {}); horizons, cost = horizons or self.config.horizons, self.config.default_cost_bps if cost_bps is None else cost_bps
        lower, upper = pd.Timestamp(start_date) if start_date else data.date.iloc[0], pd.Timestamp(end_date) if end_date else data.date.iloc[-1]
        groups: dict[str, dict[str, dict]] = {}; all_trades: list[dict] = []
        for signal in flags:
            groups[signal] = {}
            indexes = [int(i) for i, on in flags[signal].items() if on and lower <= data.date.iloc[int(i)] <= upper]
            for horizon in horizons:
                # One independent position per signal bucket: later signals that
                # arrive before the fixed exit are retained in the audit logic,
                # but not double-counted as simultaneous capital deployments.
                selected, next_available = [], -1
                for index in indexes:
                    if index >= next_available:
                        selected.append(index); next_available = index + horizon
                trades = [trade for i in selected if (trade := self._trade(data, i, signal, horizon, cost, delta_context.get(i) if signal.startswith("DELTA_") else None))]
                groups[signal][str(horizon)] = self._stats(trades); all_trades.extend(trades)
        rng = np.random.default_rng(self.config.random_seed)
        baselines: dict[str, dict[str, dict]] = {}; baseline_trades: list[dict] = []
        valid_indexes = [i for i, day in enumerate(data.date) if lower <= day <= upper]
        for signal, values in groups.items():
            baselines[signal] = {}
            for horizon in horizons:
                count = values[str(horizon)]["sample_count"]
                candidates = [i for i in valid_indexes if i + horizon < len(data)]
                picked = rng.choice(candidates, size=min(count, len(candidates)), replace=False).tolist() if count and candidates else []
                trades = [self._trade(data, int(i), signal, horizon, cost) for i in picked]
                completed = [x for x in trades if x]; baselines[signal][str(horizon)] = self._stats(completed); baseline_trades.extend(completed)
        return {"symbol": symbol.upper(), "period": {"start": lower.date().isoformat(), "end": upper.date().isoformat()}, "cost_bps_per_side": cost, "delta_confirmation_window_bars": self.config.delta_confirmation_window, "groups": groups, "random_baselines": baselines, "trades": all_trades, "baseline_trades": baseline_trades}

    def run(self, bars_by_symbol: dict[str, pd.DataFrame], **kwargs) -> dict:
        run_args = {key: value for key, value in kwargs.items() if key != "data_provenance"}
        results = {symbol.upper(): self.run_symbol(bars, symbol, **run_args) for symbol, bars in bars_by_symbol.items()}
        signals = sorted({signal for result in results.values() for signal in result["groups"]}); horizons = sorted({horizon for result in results.values() for values in result["groups"].values() for horizon in values}, key=int)
        pooled, pooled_baseline = {}, {}
        for signal in signals:
            pooled[signal], pooled_baseline[signal] = {}, {}
            for horizon in horizons:
                per_symbol = [result["groups"][signal][horizon] for result in results.values()]
                random_per_symbol = [result["random_baselines"][signal][horizon] for result in results.values()]
                pooled[signal][horizon], pooled_baseline[signal][horizon] = self._equal_weight_stats(per_symbol), self._equal_weight_stats(random_per_symbol)
        metadata = {"symbols": sorted(results), "periods": {symbol: result["period"] for symbol, result in results.items()}, "cost_bps_per_side": kwargs.get("cost_bps", self.config.default_cost_bps), "horizons": horizons, "signal_groups": signals, "formula": "JUSTIN_WEAPON", "formula_sha256": "3a11a5f2252df502f20c95c231b07090d2fcf06a42b2986d83106ce535d2b664", "random_seed": self.config.random_seed, "data_provenance": kwargs.get("data_provenance", {"source": "local_csv"})}
        fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {"symbols": results, "pooled": {"groups": pooled, "random_baselines": pooled_baseline}, "run_metadata": {**metadata, "fingerprint": fingerprint}, "assumptions": {"signal": "confirmation-day close", "entry": "next-session open", "exit": "fixed-horizon session open", "cost": "round trip: two x per-side bps", "short_return": "direction-adjusted underlying return", "overlap": "same signal bucket does not open overlapping positions", "aggregation": "equal weight across symbols; within-symbol event study", "causality": "DELTA activates only after confirmation; GPMAPRO uses only current and prior OHLCV"}}
