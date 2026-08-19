"""Evidence summaries for DELTA event records.

GPMAPRO combinations are deliberately introduced in Phase 8, after the engine
has been independently validated.
"""
from __future__ import annotations
import numpy as np


class EventAnalyticsService:
    horizons = (5, 10, 20)

    @staticmethod
    def _metrics(records: list[dict], horizon: int) -> dict:
        values = [record["forward"].get(str(horizon)) for record in records]; values = [value for value in values if value]
        if not values: return {"sample_size": 0, "hit_rate": None, "avg_return": None, "median_return": None, "avg_mfe": None, "avg_mae": None}
        returns = np.asarray([item["return_pct"] for item in values])
        return {"sample_size": len(values), "hit_rate": float((returns > 0).mean() * 100), "avg_return": float(returns.mean()), "median_return": float(np.median(returns)), "avg_mfe": float(np.mean([item["mfe_pct"] for item in values])), "avg_mae": float(np.mean([item["mae_pct"] for item in values]))}

    def analyze(self, records: list[dict]) -> dict:
        return {"event_type_performance": {event_type: {str(horizon): self._metrics([record for record in records if record["delta"]["delta_type"] == event_type], horizon) for horizon in self.horizons} for event_type in ("LOW", "HIGH")}}
