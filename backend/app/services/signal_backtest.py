"""Causal event-study backtest for DELTA, GPMAPRO and their combinations.

This is deliberately an event-return study, not a portfolio optimiser: each
signal is evaluated independently at the close where it becomes knowable.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmaapro_engine import GpmaAproEngine
from app.services.gpmapro_engine import GpmaProEngine
from app.services.research_metadata import research_run_metadata


@dataclass(frozen=True)
class SignalBacktestConfig:
    horizons: tuple[int, ...] = (5, 10, 20)
    default_cost_bps: float = 10.0
    delta_confirmation_window: int = 5
    random_seed: int = 20260813
    bootstrap_samples: int = 1_000
    minimum_trades: int = 30
    out_of_sample_fraction: float = 0.25


class SignalBacktestService:
    def __init__(self, config: SignalBacktestConfig = SignalBacktestConfig()):
        self.config, self.gpma, self.gpma2 = config, GpmaProEngine(), GpmaAproEngine()

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
        gpma2 = self.gpma2.calculate(bars).copy().reset_index(drop=True)
        delta_low, delta_high, delta_context = self._delta_flags(data)
        window = self.config.delta_confirmation_window
        low_window = delta_low.rolling(window, min_periods=1).max().astype(bool)
        high_window = delta_high.rolling(window, min_periods=1).max().astype(bool)
        gpma1_b = data[["b1", "b2", "b3"]].any(axis=1)
        gpma1_s = data[["s1", "s2"]].any(axis=1)
        gpma2_b = gpma2[["b01", "b02", "b03", "b11", "b12", "b3", "b4"]].any(axis=1)
        gpma2_s = gpma2[["s01", "s02", "s11", "s12", "s2", "s22"]].any(axis=1)
        result = pd.DataFrame({
            "DELTA_LOW": delta_low, "DELTA_HIGH": delta_high,
            # Existing identifiers remain the stable 1.0 contract.
            "GPMAPRO_B": gpma1_b,
            "GPMAPRO_S": gpma1_s,
            "DELTA_LOW_X_B": low_window & gpma1_b,
            "DELTA_HIGH_X_S": high_window & gpma1_s,
            "GPMA2_B": gpma2_b,
            "GPMA2_S": gpma2_s,
            "DELTA_LOW_X_GPMA2_B": low_window & gpma2_b,
            "DELTA_HIGH_X_GPMA2_S": high_window & gpma2_s,
        })
        result.attrs["delta_context"] = delta_context
        return result

    @staticmethod
    def _side(name: str) -> int:
        return -1 if name in {"DELTA_HIGH", "GPMAPRO_S", "DELTA_HIGH_X_S", "GPMA2_S", "DELTA_HIGH_X_GPMA2_S"} else 1

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

    def _candidate(self, version: str, signal: str, horizon: str, stats: dict, baseline: dict) -> dict:
        average = stats.get("average_net_return")
        random_average = baseline.get("average_net_return")
        edge = average - random_average if average is not None and random_average is not None else None
        count = int(stats.get("sample_count", 0))
        ci_low = (stats.get("net_return_ci_95") or [None, None])[0]
        if count < self.config.minimum_trades:
            verdict = "INSUFFICIENT_SAMPLE"
        elif edge is None or edge <= 0 or average is None or average <= 0:
            verdict = "NO_EDGE"
        elif ci_low is not None and ci_low > 0:
            verdict = "OOS_CANDIDATE"
        else:
            verdict = "WATCH"
        return {"version": version, "signal": signal, "horizon": int(horizon), "sample_count": count, "average_net_return": average, "random_baseline_return": random_average, "edge_vs_random": edge, "net_return_ci_95": stats.get("net_return_ci_95", [None, None]), "verdict": verdict}

    def _version_comparison(self, pooled: dict, baselines: dict, horizons: list[str]) -> dict:
        definitions = {
            "indicator_only": {
                "BUY": {"1.0": "GPMAPRO_B", "2.0": "GPMA2_B"},
                "SELL": {"1.0": "GPMAPRO_S", "2.0": "GPMA2_S"},
            },
            "delta_confirmed": {
                "BUY": {"1.0": "DELTA_LOW_X_B", "2.0": "DELTA_LOW_X_GPMA2_B"},
                "SELL": {"1.0": "DELTA_HIGH_X_S", "2.0": "DELTA_HIGH_X_GPMA2_S"},
            },
        }
        setups: dict[str, dict] = {}
        all_candidates: list[dict] = []
        for setup, actions in definitions.items():
            setups[setup] = {}
            for action, versions in actions.items():
                candidates = [
                    self._candidate(version, signal, horizon, pooled[signal][horizon], baselines[signal][horizon])
                    for version, signal in versions.items() for horizon in horizons
                ]
                eligible = [item for item in candidates if item["verdict"] != "INSUFFICIENT_SAMPLE"]
                winner = max(eligible, key=lambda item: (item["edge_vs_random"] if item["edge_vs_random"] is not None else -float("inf"), item["average_net_return"] if item["average_net_return"] is not None else -float("inf"))) if eligible else None
                setups[setup][action] = {"candidates": candidates, "winner": winner, "status": winner["verdict"] if winner else "INSUFFICIENT_SAMPLE"}
                all_candidates.extend({**item, "setup": setup, "action": action} for item in candidates)
        def best(action: str) -> dict | None:
            candidates = [item for item in all_candidates if item["action"] == action and item["verdict"] in {"OOS_CANDIDATE", "WATCH"}]
            return max(candidates, key=lambda item: (item["verdict"] == "OOS_CANDIDATE", item["edge_vs_random"] or -float("inf"))) if candidates else None
        return {
            "minimum_trades": self.config.minimum_trades,
            "execution": "signal-day close is observed; trade at next-session open",
            "sell_semantics": "SELL measures decline avoided after a bearish signal; it is not a short-selling order",
            "setups": setups,
            "best_buy": best("BUY"),
            "best_sell": best("SELL"),
        }

    def run_symbol(self, bars: pd.DataFrame, symbol: str, *, horizons: tuple[int, ...] | None = None, cost_bps: float | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
        data = bars.copy().sort_values("date").reset_index(drop=True); data["date"] = pd.to_datetime(data.date)
        flags = self._signals(data); delta_context = flags.attrs.get("delta_context", {}); horizons, cost = horizons or self.config.horizons, self.config.default_cost_bps if cost_bps is None else cost_bps
        lower, upper = pd.Timestamp(start_date) if start_date else data.date.iloc[0], pd.Timestamp(end_date) if end_date else data.date.iloc[-1]
        eligible_dates = data.loc[(data.date >= lower) & (data.date <= upper), "date"].reset_index(drop=True)
        split_index = min(len(eligible_dates) - 1, max(0, int(len(eligible_dates) * (1 - self.config.out_of_sample_fraction))))
        out_of_sample_start = eligible_dates.iloc[split_index] if len(eligible_dates) else upper
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
        oos_groups, oos_baselines = {}, {}
        for signal in groups:
            oos_groups[signal], oos_baselines[signal] = {}, {}
            for horizon in horizons:
                signal_trades = [trade for trade in all_trades if trade["signal"] == signal and trade["horizon"] == horizon and pd.Timestamp(trade["date"]) >= out_of_sample_start]
                oos_groups[signal][str(horizon)] = self._stats(signal_trades)
                candidates = [i for i in valid_indexes if data.date.iloc[i] >= out_of_sample_start and i + horizon < len(data)]
                picked = rng.choice(candidates, size=min(len(signal_trades), len(candidates)), replace=False).tolist() if signal_trades and candidates else []
                random_trades = [trade for i in picked if (trade := self._trade(data, int(i), signal, horizon, cost))]
                oos_baselines[signal][str(horizon)] = self._stats(random_trades)
        return {"symbol": symbol.upper(), "period": {"start": lower.date().isoformat(), "end": upper.date().isoformat()}, "validation_split": {"method": "chronological_holdout", "out_of_sample_fraction": self.config.out_of_sample_fraction, "out_of_sample_start": out_of_sample_start.date().isoformat()}, "cost_bps_per_side": cost, "delta_confirmation_window_bars": self.config.delta_confirmation_window, "groups": groups, "random_baselines": baselines, "out_of_sample_groups": oos_groups, "out_of_sample_random_baselines": oos_baselines, "trades": all_trades, "baseline_trades": baseline_trades}

    def run(self, bars_by_symbol: dict[str, pd.DataFrame], **kwargs) -> dict:
        run_args = {key: value for key, value in kwargs.items() if key != "data_provenance"}
        results = {symbol.upper(): self.run_symbol(bars, symbol, **run_args) for symbol, bars in bars_by_symbol.items()}
        signals = sorted({signal for result in results.values() for signal in result["groups"]}); horizons = sorted({horizon for result in results.values() for values in result["groups"].values() for horizon in values}, key=int)
        pooled, pooled_baseline, pooled_oos, pooled_oos_baseline = {}, {}, {}, {}
        for signal in signals:
            pooled[signal], pooled_baseline[signal], pooled_oos[signal], pooled_oos_baseline[signal] = {}, {}, {}, {}
            for horizon in horizons:
                per_symbol = [result["groups"][signal][horizon] for result in results.values()]
                random_per_symbol = [result["random_baselines"][signal][horizon] for result in results.values()]
                pooled[signal][horizon], pooled_baseline[signal][horizon] = self._equal_weight_stats(per_symbol), self._equal_weight_stats(random_per_symbol)
                oos_per_symbol = [result["out_of_sample_groups"][signal][horizon] for result in results.values()]
                oos_random_per_symbol = [result["out_of_sample_random_baselines"][signal][horizon] for result in results.values()]
                pooled_oos[signal][horizon], pooled_oos_baseline[signal][horizon] = self._equal_weight_stats(oos_per_symbol), self._equal_weight_stats(oos_random_per_symbol)
        comparison = self._version_comparison(pooled_oos, pooled_oos_baseline, horizons)
        comparison["validation"] = "chronological final-25% holdout; full-sample results are descriptive only"
        provenance = kwargs.get("data_provenance", {"source": "local_csv"})
        parameters = {"symbols": sorted(results), "periods": {symbol: result["period"] for symbol, result in results.items()}, "cost_bps_per_side": kwargs.get("cost_bps", self.config.default_cost_bps), "horizons": horizons, "signal_groups": signals, "random_seed": self.config.random_seed}
        stable_context = {"formula": "JUSTIN_WEAPON", "formula_sha256": "3a11a5f2252df502f20c95c231b07090d2fcf06a42b2986d83106ce535d2b664"}
        audit = research_run_metadata(parameters=parameters, data_provenance=provenance, stable_context=stable_context)
        metadata = {**parameters, **stable_context, "data_provenance": provenance, **audit}
        return {"symbols": results, "pooled": {"groups": pooled, "random_baselines": pooled_baseline, "out_of_sample_groups": pooled_oos, "out_of_sample_random_baselines": pooled_oos_baseline}, "version_comparison": comparison, "run_metadata": metadata, "assumptions": {"signal": "confirmation-day close", "entry": "next-session open", "exit": "fixed-horizon session open", "cost": "round trip: two x per-side bps", "short_return": "direction-adjusted underlying return", "overlap": "same signal bucket does not open overlapping positions", "aggregation": "equal weight across symbols; within-symbol event study", "validation": "version winner uses only the chronological final-25% holdout", "causality": "DELTA activates only after confirmation; GPMAPRO 1.0 and 2.0 use only current and prior OHLCV"}}
