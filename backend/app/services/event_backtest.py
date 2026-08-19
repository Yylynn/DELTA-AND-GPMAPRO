"""DELTA event evidence, independent of anchored-VWAP and price targets."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from app.quant.delta_time import ITDDeltaEngine
from app.quant.indicators import wilder_atr


@dataclass
class EventBacktestService:
    horizons: tuple[int, ...] = (5, 10, 20)

    @staticmethod
    def _events(analysis: dict) -> list[dict]:
        return [{"event_id": point["id"], "event_type": point["type"], "actual_date": point["actual_date"], "confirmed_on": point["confirmed_on"], "tradable_on": point["tradable_on"]} for point in analysis.get("confirmed_points", []) if point.get("tradable_on")]

    @staticmethod
    def _forward(data: pd.DataFrame, start: int, horizon: int) -> dict | None:
        end = start + horizon
        if end >= len(data): return None
        entry = float(data.open.iloc[start]); future = data.iloc[start:end + 1]
        return {"return_pct": float((float(data.open.iloc[end]) - entry) / entry * 100), "mfe_pct": float((future.high.max() - entry) / entry * 100), "mae_pct": float((future.low.min() - entry) / entry * 100)}

    @staticmethod
    def _aggregate(records: list[dict], horizon: int) -> dict:
        values = [record["forward"][str(horizon)] for record in records if record["forward"].get(str(horizon))]
        if not values: return {"sample_count": 0, "average_return": None, "median_return": None, "mfe": None, "mae": None}
        returns = np.asarray([item["return_pct"] for item in values])
        return {"sample_count": len(values), "average_return": float(returns.mean()), "median_return": float(np.median(returns)), "mfe": float(np.mean([item["mfe_pct"] for item in values])), "mae": float(np.mean([item["mae_pct"] for item in values]))}

    def run(self, bars: pd.DataFrame, *, start_date: str | None, end_date: str | None) -> dict:
        data = bars.copy().sort_values("date").reset_index(drop=True); data["date"] = pd.to_datetime(data.date); data["atr"] = wilder_atr(data)
        analysis = ITDDeltaEngine().analyze(data)
        if analysis["status"] == "INSUFFICIENT_HISTORY": return {"event_results": [], "groups": {}, "reason_code": "INSUFFICIENT_HISTORY"}
        lower, upper = pd.Timestamp(start_date) if start_date else data.date.iloc[0], pd.Timestamp(end_date) if end_date else data.date.iloc[-1]
        records = []
        for event in self._events(analysis):
            positions = data.index[data.date == pd.Timestamp(event["tradable_on"])]
            if not len(positions): continue
            position = int(positions[0]); timestamp = data.date.iloc[position]
            if not lower <= timestamp <= upper: continue
            records.append({"symbol": None, "timestamp": timestamp.date().isoformat(), "actual_date": event["actual_date"], "signal_known_at": event["confirmed_on"], "entry_date": event["tradable_on"], "entry_price": float(data.open.iloc[position]), "delta": {"delta_type": event["event_type"], "delta_confirmed_at": event["confirmed_on"]}, "forward": {str(horizon): self._forward(data, position, horizon) for horizon in self.horizons}})
        groups = {event_type: {str(horizon): self._aggregate([record for record in records if record["delta"]["delta_type"] == event_type], horizon) for horizon in self.horizons} for event_type in ("LOW", "HIGH")}
        return {"event_results": records, "groups": groups, "reason_code": None}
