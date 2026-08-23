"""Conservative NYSE session alignment for point-in-time news research."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay,
    USMartinLutherKingJr, USMemorialDay, USPresidentsDay,
    USThanksgivingDay, nearest_workday,
)

NY = ZoneInfo("America/New_York")


class _NYSEHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("NewYear", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def is_session(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    holidays = _NYSEHolidays().holidays(pd.Timestamp(day), pd.Timestamp(day))
    return holidays.empty


def next_session(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not is_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def earliest_trade_at(value: str | datetime) -> str:
    """Return the next NYSE open strictly after publication (no same-day fills)."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    local = stamp.tz_convert(NY)
    return datetime.combine(next_session(local.date()), time(9, 30), NY).isoformat()
