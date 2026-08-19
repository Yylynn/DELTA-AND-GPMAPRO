"""Point-in-time / repaint audit for the DELTA ITD engine.

Usage (from backend):
    python scripts/audit_lookahead.py ../../data/futu_snapshots/US_AAPL_1D_QFQ_....csv

The tool is deliberately diagnostic: findings are returned as JSON and a
non-zero exit code is reserved for malformed input, not an expected finding.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from app.quant.delta_time import ITDDeltaEngine
from app.services.strategy_lab import StrategyLabService


def _point_key(point: dict) -> tuple[str, str, str]:
    return point["id"], point["type"], point["date"]


def _forecast_key(item: dict) -> tuple[str, str, str, str]:
    return item["published_at"], item["event_type"], item["window_start"], item["window_end"]


def audit(frame: pd.DataFrame) -> dict:
    data = frame.copy().sort_values("date").reset_index(drop=True)
    data["date"] = pd.to_datetime(data["date"])
    engine = ITDDeltaEngine()
    full = engine.analyze(data)
    points = [point for point in full.get("points", []) if point.get("confirmed")]

    # A point drawn at `date` but confirmed after `date` is a retrospective
    # annotation. It is valid for structure review, but was unavailable to a
    # trader on the chart date.
    retrospective = [
        point for point in points
        if date.fromisoformat(point["date"]) < date.fromisoformat(point["confirmed_at"])
    ]

    # Direct replay: before `confirmed_at`, the final full-sample marker must
    # not yet be treated as known. This quantifies the chart's visual repaint.
    unavailable_before_confirmation = 0
    for point in retrospective:
        cutoff = data.index[data.date < pd.Timestamp(point["confirmed_at"])]
        if not len(cutoff):
            continue
        replay = engine.analyze(data.iloc[: int(cutoff[-1]) + 1])
        if _point_key(point) not in {_point_key(item) for item in replay.get("points", []) if item.get("confirmed")}:
            unavailable_before_confirmation += 1

    # Mutate future OHLCV for several fixed cutoffs. A causal forecast replay
    # must leave all forecasts published no later than each cutoff unchanged.
    # Replaying every prefix of a multi-year daily data set is deliberately
    # expensive. A fixed 500-bar slice still has several complete 118-day
    # structures and keeps this smoke audit practical for an interactive run.
    replay_data = data.tail(min(500, len(data))).reset_index(drop=True)
    lab = StrategyLabService()
    original = lab._features(replay_data)[1]
    cutoffs = [replay_data.date.iloc[index] for index in (150, 260, 370) if index < len(replay_data) - 20]
    stable, checks = True, []
    mutated = data.copy()
    for cutoff in cutoffs:
        changed = replay_data.copy()
        changed.loc[changed.date > cutoff, ["open", "high", "low", "close", "volume"]] *= 3.0
        replay = lab._features(changed)[1]
        expected = {_forecast_key(item) for item in original if pd.Timestamp(item["published_at"]) <= cutoff}
        observed = {_forecast_key(item) for item in replay if pd.Timestamp(item["published_at"]) <= cutoff}
        passed = expected == observed
        stable &= passed
        checks.append({"cutoff": cutoff.date().isoformat(), "passed": passed, "forecast_count": len(expected)})

    return {
        "bars": len(data),
        "period": {"start": data.date.iloc[0].date().isoformat(), "end": data.date.iloc[-1].date().isoformat()},
        "historical_structures": len(points),
        "retrospective_structures": len(retrospective),
        "retrospective_structure_rate": round(len(retrospective) / len(points), 4) if points else None,
        "unavailable_before_confirmation": unavailable_before_confirmation,
        "tradable_after_confirmation": sum(bool(point.get("tradable_on")) and point["confirmed_on"] < point["tradable_on"] for point in points),
        "trading_marker_verdict": "PASS" if all(point.get("actual_date") and point.get("confirmed_on") and point.get("tradable_on") and point["actual_date"] < point["confirmed_on"] < point["tradable_on"] for point in points) else "FAIL",
        "forecast_tail_mutation_verdict": "PASS" if stable else "FAIL",
        "forecast_tail_mutation_checks": checks,
        "note": "Retrospective structures are expected for review. PASS means trade markers are delayed to confirmation and the following session, while forecasts remain tail-mutation invariant.",
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/audit_lookahead.py PATH_TO_OHLCV_CSV")
    source = Path(sys.argv[1])
    if not source.is_file():
        raise SystemExit(f"CSV not found: {source}")
    print(json.dumps(audit(pd.read_csv(source)), ensure_ascii=False, indent=2))
