"""Point-in-time Decision Validation replay; this is not a trading backtest."""
from __future__ import annotations
import statistics
import pandas as pd

from app.config.backtest_config import DECISION_BACKTEST_CONFIG, DecisionBacktestConfig
from app.services.decision_engine import DecisionEngine
from app.services.evidence_engine import EvidenceEngine


class DecisionBacktestService:
    def __init__(self, config: DecisionBacktestConfig = DECISION_BACKTEST_CONFIG, evidence_engine: EvidenceEngine | None = None, decision_engine: DecisionEngine | None = None):
        self.config, self.evidence_engine, self.decision_engine = config, evidence_engine or EvidenceEngine(), decision_engine or DecisionEngine()

    def _outcomes(self, data: pd.DataFrame, index: int) -> dict:
        entry = float(data.close.iloc[index]); result = {}
        for horizon in self.config.horizons:
            if index + horizon >= len(data): result[str(horizon)] = {"forward_return": None, "mfe": None, "mae": None}; continue
            future = data.iloc[index + 1:index + horizon + 1]
            result[str(horizon)] = {"forward_return": float(data.close.iloc[index + horizon] / entry - 1), "mfe": float(future.high.max() / entry - 1), "mae": float(future.low.min() / entry - 1)}
        return result

    @staticmethod
    def _signature(confirmations: dict) -> str:
        labels = (("delta", "DELTA"), ("trend", "TREND"), ("signal", "SIGNAL"), ("volume", "VOLUME"), ("historical", "HISTORICAL"))
        return "|".join(label for key, label in labels if confirmations.get(key)) or "NONE"

    def replay(self, bars: pd.DataFrame, symbol: str, timeframe: str, start_date: str | None = None, end_date: str | None = None, sampling_mode: str | None = None) -> list[dict]:
        mode = (sampling_mode or self.config.default_sampling_mode).upper()
        if mode not in {"DAILY", "TRANSITION"}: raise ValueError("sampling_mode must be DAILY or TRANSITION")
        data = bars.copy().sort_values("date").reset_index(drop=True); data["date"] = pd.to_datetime(data.date)
        lower = pd.Timestamp(start_date) if start_date else data.date.iloc[0]; upper = pd.Timestamp(end_date) if end_date else data.date.iloc[-1]
        events, previous_state = [], None
        for index, row in data.iterrows():
            if not lower <= row.date <= upper: continue
            # Evidence internally truncates all indicator and historical inputs at this exact date.
            snapshot = self.evidence_engine.snapshot(data, symbol, timeframe, row.date.date().isoformat())
            decision = self.decision_engine.decide(snapshot)
            changed = decision["state"] != previous_state
            previous_state = decision["state"]
            if mode == "TRANSITION" and not changed: continue
            confirmations = decision["confirmations"]
            active_signals = [item["id"].split("_")[-1].upper() for item in snapshot["evidence"] if item.get("source") == "GPMAPRO" and item.get("category") == "SIGNAL" and item.get("status") in {"ACTIVE", "RECENT"}]
            events.append({"symbol": symbol.upper(), "timeframe": timeframe, "date": row.date.date().isoformat(), "state": decision["state"], "confidence": decision["confidence"], "bullish_score": decision["scores"]["bullish"], "bearish_score": decision["scores"]["bearish"], "evidence_balance": decision["evidence_balance"], "confirmations": confirmations, "confirmation_signature": self._signature(confirmations), "active_signal_codes": active_signals, "risk_factor_count": len(decision["risk_factors"]), "conflict_count": len(snapshot["conflicts"]), "decision_codes": [reason.split(":", 1)[0] for reason in decision["reasons"]], "outcomes": self._outcomes(data, index), "decision_trace": decision["decision_trace"], "missing_conditions": decision["missing_conditions"], "risk_factors": decision["risk_factors"]})
        return events

    @staticmethod
    def _stats(events: list[dict]) -> dict:
        result = {"sample_count": len(events)}
        for h in (5, 10, 20):
            available = [event["outcomes"][str(h)] for event in events if event["outcomes"][str(h)]["forward_return"] is not None]
            result[f"sample_count_{h}"] = len(available)
            for metric in ("forward_return", "mfe", "mae"):
                values = [float(x[metric]) for x in available]
                prefix = "return" if metric == "forward_return" else metric
                result[f"avg_{prefix}_{h}"] = float(statistics.mean(values)) if values else None
                result[f"median_{prefix}_{h}"] = float(statistics.median(values)) if values else None
            values = [float(x["forward_return"]) for x in available]
            result[f"positive_rate_{h}"] = sum(x > 0 for x in values) / len(values) if values else None
            result[f"excursion_asymmetry_{h}"] = (result[f"median_mfe_{h}"] - abs(result[f"median_mae_{h}"])) if values else None
        result["sample_quality"] = "LOW_SAMPLE" if len(events) < 10 else "MODERATE_SAMPLE" if len(events) < 30 else "STRONGER_SAMPLE"
        return result

    def summary(self, events: list[dict], *, symbol: str, sampling_mode: str, start_date: str | None, end_date: str | None) -> dict:
        states = {state: self._stats([event for event in events if event["state"] == state]) for state in ("BUY", "WATCH", "WAIT", "RISK")}
        return {"symbol": symbol.upper(), "sampling_mode": sampling_mode.upper(), "period": {"start": start_date, "end": end_date}, "states": states, "total_events": len(events)}

    def breakdown(self, events: list[dict], group_by: str) -> dict:
        allowed = {"confidence", "confirmations", "delta", "volume", "signal", "conflict", "signature"}
        if group_by not in allowed: raise ValueError("group_by must be confidence, confirmations, delta, volume, signal, conflict or signature")
        groups: dict[str, list[dict]] = {}
        for event in events:
            if group_by == "signal":
                # Preserve B1/B2/B3/S1/S2 identity instead of collapsing signal
                # evidence into a single boolean.  Events with no live signal are
                # represented explicitly for a complete, non-cherry-picked view.
                codes = event.get("active_signal_codes") or ["NONE"]
                for code in codes: groups.setdefault(code, []).append(event)
                continue
            if group_by == "confidence":
                c = event["confidence"]; key = "<0.40" if c < .40 else "0.40-0.55" if c < .55 else "0.55-0.70" if c < .70 else "0.70-0.85" if c < .85 else ">=0.85"
            elif group_by == "confirmations": key = str(event["confirmations"]["count"])
            elif group_by == "conflict": key = "0" if event["conflict_count"] == 0 else "1" if event["conflict_count"] == 1 else "2+"
            elif group_by == "signature": key = event["confirmation_signature"]
            else: key = "true" if event["confirmations"].get(group_by) else "false"
            groups.setdefault(key, []).append(event)
        return {"group_by": group_by, "groups": {key: self._stats(value) for key, value in groups.items() if group_by != "signature" or len(value) >= self.config.min_signature_samples}}
