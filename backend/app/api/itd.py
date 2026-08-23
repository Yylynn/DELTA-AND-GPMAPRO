import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.api.data import bars_for_source
from app.quant.delta_time import ITDConfig, ITDDeltaEngine, fixed_cycle_grid

router = APIRouter(tags=["DELTA ITD"])
config_store = Path(__file__).resolve().parents[3] / "data" / "itd_config.json"


def project_display_dates(source_frame: pd.DataFrame, display_frame: pd.DataFrame, timeframe: str) -> dict[str, str]:
    """Map a daily ITD date onto the bar that represents its display period.

    The model always runs on daily bars.  Lightweight Charts, however, only
    knows the actual weekly/monthly bar dates, so annotations must use that
    period's final trading date instead of an arbitrary daily date.
    """
    source_dates = pd.to_datetime(source_frame["date"])
    display_dates = pd.to_datetime(display_frame["date"])
    if timeframe == "1d":
        return {value.date().isoformat(): value.date().isoformat() for value in source_dates}
    frequency = "W-FRI" if timeframe == "1w" else "M"
    display_by_period = {value.to_period(frequency): value.date().isoformat() for value in display_dates}
    return {
        value.date().isoformat(): display_by_period.get(value.to_period(frequency), value.date().isoformat())
        for value in source_dates
    }


def load_config() -> ITDConfig:
    if not config_store.exists():
        return ITDConfig()
    return ITDConfig.model_validate(json.loads(config_store.read_text(encoding="utf-8")))


@router.get("/itd/config")
def get_config():
    return load_config()


@router.put("/itd/config")
def put_config(config: ITDConfig):
    config_store.parent.mkdir(parents=True, exist_ok=True)
    config_store.write_text(json.dumps(config.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return config


@router.get("/itd/{symbol}")
def itd_structure(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        # DELTA must use the same immutable OHLCV input as the overlaid
        # GPMAPRO series; otherwise its dates disappear outside local CSV.
        frame, _ = bars_for_source(symbol, timeframe, snapshot_id)
        source_frame, _ = bars_for_source(symbol, "1d", snapshot_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "未找到该代码数据")
    # The skill defines an ITD unit in trading bars.  Always calculate on the
    # immutable daily snapshot, then let the client map its dated annotations
    # onto weekly/monthly display bars.
    analysis = ITDDeltaEngine(load_config()).analyze(source_frame)
    source_dates = [value.date() for value in pd.to_datetime(source_frame["date"])]
    display_dates = [value.date() for value in pd.to_datetime(frame["date"])]
    display_projection = project_display_dates(source_frame, frame, timeframe)
    # Keep raw daily dates for audit and prediction calculations, while every
    # chart annotation gets a date guaranteed to exist on this chart's axis.
    for point in analysis["points"]:
        point["display_date"] = display_projection.get(point["date"], point["date"])
    for ibp in analysis.get("reversal", {}).get("ibps", []):
        ibp["display_date"] = display_projection.get(ibp["date"], ibp["date"])
    for window in analysis.get("reversal", {}).get("windows", []):
        window["display_start"] = display_projection.get(window["window_start"], window["window_start"])
        window["display_end"] = display_projection.get(window["window_end"], window["window_end"])
    if analysis.get("boundary_point"):
        boundary = analysis["boundary_point"]
        boundary["display_date"] = display_projection.get(boundary["date"], boundary["date"])
    # The imported daily source sequence is the single anchor.  This intentionally
    # ignores viewport and aggregation boundaries when assigning phase positions.
    analysis["grid_anchor_date"] = source_dates[0].isoformat() if source_dates else None
    analysis["grid_lines"] = [
        {**line, "display_date": display_projection.get(line["anchor_date"], line["anchor_date"])}
        for line in fixed_cycle_grid(source_dates, source_dates)
    ]
    return {"symbol": symbol.upper(), "timeframe": timeframe, **analysis}
