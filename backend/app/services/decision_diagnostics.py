"""Cross-symbol aggregation of completed Decision Validation events only."""
from __future__ import annotations
import statistics
from collections import Counter
from datetime import date
from pathlib import Path
import json
import pandas as pd
from app.config.diagnostics_config import DIAGNOSTICS_CONFIG, DiagnosticsConfig
from app.services.decision_backtest import DecisionBacktestService
from app.quant.delta_time import ManualDeltaEngine

class DecisionDiagnostics:
    def __init__(self, config: DiagnosticsConfig = DIAGNOSTICS_CONFIG, backtest: DecisionBacktestService | None = None): self.config, self.backtest = config, backtest or DecisionBacktestService()

    def _state_stats(self, events: list[dict]) -> dict: return self.backtest._stats(events)
    def _eligible(self, per_symbol: dict, state: str) -> list[tuple[str, dict]]:
        return [(symbol, values[state]) for symbol, values in per_symbol.items() if values[state]["sample_count_10"] >= self.config.min_symbol_state_samples]
    def _cross_state(self, per_symbol: dict, state: str) -> dict:
        eligible = self._eligible(per_symbol, state); medians = [x["median_return_10"] for _, x in eligible if x["median_return_10"] is not None]
        positive = sum(x > 0 for x in medians)
        return {"eligible_symbols": len(medians), "positive_median_symbols": positive, "symbol_positive_breadth": positive / len(medians) if medians else None, "cross_symbol_median_return_10": float(statistics.median(medians)) if medians else None}
    def _marginal(self, events_by_symbol: dict[str, list[dict]], key: str) -> dict:
        rows, improved = [], 0
        for symbol, events in events_by_symbol.items():
            with_ = [e for e in events if e["confirmations"].get(key)]; without = [e for e in events if not e["confirmations"].get(key)]
            ws, wo = self._state_stats(with_), self._state_stats(without)
            lift = None if ws["median_return_10"] is None or wo["median_return_10"] is None else ws["median_return_10"] - wo["median_return_10"]
            rows.append({"symbol": symbol, "with": ws, "without": wo, "marginal_lift_10d": lift, "eligible": min(ws["sample_count_10"], wo["sample_count_10"]) >= self.config.min_symbol_state_samples})
            if rows[-1]["eligible"] and lift is not None and lift > 0: improved += 1
        eligible = [x for x in rows if x["eligible"]]
        return {"confirmation": key, "per_symbol": rows, "eligible_symbols": len(eligible), "improved_symbols": improved, "improvement_breadth": improved / len(eligible) if eligible else None}
    @staticmethod
    def _monotonic(groups: dict[str, dict]) -> str:
        order = ["<0.40", "0.40-0.55", "0.55-0.70", "0.70-0.85", ">=0.85"]; values = [groups[x]["median_return_10"] for x in order if x in groups and groups[x]["sample_count_10"]]
        if len(values) < 3: return "INSUFFICIENT"
        return "MONOTONIC" if all(a <= b for a, b in zip(values, values[1:])) else "PARTIAL" if values[-1] >= values[0] else "NON_MONOTONIC"
    def _delta_funnel(self, symbols: list[str], events_by_symbol: dict[str, list[dict]], start: str | None, end: str | None, bars_by_symbol: dict[str, pd.DataFrame] | None = None) -> dict:
        store = Path(__file__).resolve().parents[3] / "data" / "delta_events.json"; raw = json.loads(store.read_text(encoding="utf-8")) if store.exists() else []
        scoped = [x for x in raw if x.get("enabled", True) and x.get("symbol", "*").upper() in {"*", *[s.upper() for s in symbols]}]
        windows = ManualDeltaEngine(scoped).windows(); lower, upper = pd.Timestamp(start).date() if start else date.min, pd.Timestamp(end).date() if end else date.max
        in_range = []
        for window in windows:
            data = (bars_by_symbol or {}).get(str(next((x.get("symbol") for x in scoped if str(x.get("event_id")) == window.event_id), "")).upper())
            if data is None or window.expected_date >= pd.Timestamp(data.date.iloc[0]).date() and window.expected_date <= pd.Timestamp(data.date.iloc[-1]).date(): in_range.append(window)
        active = [w for w in in_range if w.window_end >= lower and w.window_start <= upper]
        all_events = [e for values in events_by_symbol.values() for e in values]
        evidence = sum(any(code == "DELTA_BULLISH_WINDOW" for code in e["decision_codes"]) for e in all_events)
        confirms = sum(e["confirmations"].get("delta") for e in all_events); states = sum(e["confirmations"].get("delta") and e["state"] in {"BUY", "WATCH", "RISK"} for e in all_events)
        reason = "NO_DELTA_EVENTS" if not raw else "NO_ACTIVE_WINDOWS" if not active else "DECISION_NOT_CONFIRMED" if not confirms else None
        return {"configured_events": len(scoped), "enabled_events": len(scoped), "events_inside_data_range": len(in_range), "outside_data_range": len(scoped) - len(in_range), "active_windows": len(active), "delta_low_events": sum(w.event_type.value == "LOW" for w in in_range), "delta_high_events": sum(w.event_type.value == "HIGH" for w in in_range), "delta_low_windows": sum(w.event_type.value == "LOW" for w in active), "delta_high_windows": sum(w.event_type.value == "HIGH" for w in active), "low_bullish_evidence": evidence, "high_bearish_evidence": 0, "evidence_snapshots": evidence, "decision_confirmations": confirms, "bullish_delta_confirmations": confirms, "bearish_delta_confirmations": 0, "buy_watch_risk_with_delta": states, "coverage_ratios": {"events_in_data_range_over_configured": len(in_range) / len(scoped) if scoped else None, "evidence_over_active_windows": evidence / len(active) if active else None, "decision_over_evidence": confirms / evidence if evidence else None}, "zero_confirmation_reason": reason}
    def run(self, bars_by_symbol: dict[str, pd.DataFrame], timeframe: str, start_date: str | None, end_date: str | None, sampling_mode: str) -> dict:
        events_by_symbol = {symbol: self.backtest.replay(bars, symbol, timeframe, start_date, end_date, sampling_mode) for symbol, bars in bars_by_symbol.items()}
        per_symbol = {symbol: {state: self._state_stats([e for e in events if e["state"] == state]) for state in ("BUY", "WATCH", "WAIT", "RISK")} for symbol, events in events_by_symbol.items()}
        all_events = [e for events in events_by_symbol.values() for e in events]; pooled = {state: self._state_stats([e for e in all_events if e["state"] == state]) for state in ("BUY", "WATCH", "WAIT", "RISK")}
        cross = {state: self._cross_state(per_symbol, state) for state in pooled}
        buy_watch = None if pooled["BUY"]["median_return_10"] is None or pooled["WATCH"]["median_return_10"] is None else pooled["BUY"]["median_return_10"] - pooled["WATCH"]["median_return_10"]
        risk_wait = None if pooled["RISK"]["median_return_10"] is None or pooled["WAIT"]["median_return_10"] is None else pooled["RISK"]["median_return_10"] - pooled["WAIT"]["median_return_10"]
        confidence = self.backtest.breakdown(all_events, "confidence")["groups"]
        years = {year: {state: self._state_stats([e for e in all_events if e["date"][:4] == year and e["state"] == state]) for state in pooled} for year in sorted({e["date"][:4] for e in all_events})}
        marginal = {key: self._marginal(events_by_symbol, key) for key in ("delta", "trend", "signal", "volume", "historical")}
        funnel = self._delta_funnel(list(bars_by_symbol), events_by_symbol, start_date, end_date, bars_by_symbol)
        flags = {"buy_separation": "INSUFFICIENT" if pooled["BUY"]["sample_count_10"] < self.config.min_pooled_samples else "PASS" if buy_watch is not None and buy_watch > 0 and (cross["BUY"]["symbol_positive_breadth"] or 0) >= .5 else "WEAK", "risk_separation": "INSUFFICIENT" if pooled["RISK"]["sample_count_10"] < self.config.min_pooled_samples else "PASS" if risk_wait is not None and risk_wait < 0 else "WEAK", "confidence_calibration": self._monotonic(confidence), "delta_coverage": "INSUFFICIENT" if not funnel["decision_confirmations"] else "PASS", "volume_incremental_value": "INSUFFICIENT" if not marginal["volume"]["eligible_symbols"] else "PASS" if (marginal["volume"]["improvement_breadth"] or 0) >= .5 else "WEAK"}
        return {"symbols": list(bars_by_symbol), "timeframe": timeframe, "sampling_mode": sampling_mode.upper(), "total_events": len(all_events), "pooled": pooled, "per_symbol": per_symbol, "cross_symbol": cross, "comparisons": {"buy_watch_spread_10d": buy_watch, "risk_wait_spread_10d": risk_wait}, "confidence": {"groups": confidence, "monotonicity": self._monotonic(confidence)}, "confirmations": self.backtest.breakdown(all_events, "confirmations"), "marginal_confirmation_value": marginal, "delta_funnel": funnel, "signal_breakdown": self.backtest.breakdown(all_events, "signal"), "yearly": years, "robustness_flags": flags}
