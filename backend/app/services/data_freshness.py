from __future__ import annotations

from datetime import date
import pandas as pd


def freshness_snapshot(latest_bar_date: str | date | None, bars: int, as_of: date | None = None) -> dict:
    if latest_bar_date is None:
        return {"latest_bar_date": None, "bars": bars, "days_since_latest_bar": None, "freshness": "UNKNOWN"}
    try:
        latest = pd.Timestamp(latest_bar_date).date()
    except (TypeError, ValueError):
        return {"latest_bar_date": None, "bars": bars, "days_since_latest_bar": None, "freshness": "UNKNOWN"}
    days = max(0, ((as_of or date.today()) - latest).days)
    freshness = "CURRENT" if days <= 3 else "STALE" if days <= 7 else "VERY_STALE"
    return {"latest_bar_date": latest.isoformat(), "bars": bars, "days_since_latest_bar": days, "freshness": freshness}
