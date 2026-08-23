"""Futu-authoritative GPMA2 data and immutable trace snapshots."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.api.data import bars_for_source
from app.services.futu_gpmapro_trace import FutuGpmaProTraceClient
from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS
from app.services.gpmapro_trace import TraceSnapshotService

router = APIRouter(tags=["GPMA2"])
SHORT_NAME = "GPMA2"
TRACE_SHORT_NAME = "GPMA2TRACE"
FULL_NAME = "GPMA 2.0"
EMA_PAIRS = (("E8", "E8R", "E8G"), ("E10", "E10R", "E10G"), ("E12", "E12R", "E12G"), ("E15", "E15R", "E15G"), ("E20", "E20R", "E20G"), ("E40", "E40R", "E40G"), ("E45", "E45R", "E45G"), ("E50", "E50R", "E50G"), ("E55", "E55R", "E55G"), ("E60", "E60R", "E60G"))
TEXT_LABELS = ("B01", "B02", "B03", "B11", "B12", "B3", "B4", "S01", "S02", "S11", "S12", "S2", "S22")
ICON_NODES = (("top", 4), ("bottom", 5), ("top", 2), ("bottom", 1))
ICON_VISUALS = {4: "top-face", 5: "bottom-face", 2: "top-arrow-2", 1: "bottom-arrow-2"}
traces = TraceSnapshotService(Path(__file__).resolve().parents[3] / "data" / "gpma2_trace", namespace="GPMA2")


def _number(row: pd.Series, name: str) -> float | None:
    value = row.get(name)
    return None if value is None or pd.isna(value) else float(value)


def _nodes(row: pd.Series) -> list[dict]:
    nodes: list[dict] = []
    for index, label in enumerate(TEXT_LABELS, start=1):
        value = _number(row, f"LINE{index}")
        if value not in (None, 0.0): nodes.append({"kind": "text", "formula": "DRAWTEXT", "text": label, "price": value})
    for offset, (direction, icon_id) in enumerate(ICON_NODES, start=14):
        value = _number(row, f"LINE{offset}")
        if value not in (None, 0.0): nodes.append({"kind": "icon", "formula": "DRAWICON", "icon_id": icon_id, "visual": ICON_VISUALS[icon_id], "price": value, "direction": direction})
    return nodes


def _trace_nodes(row: pd.Series) -> list[dict]:
    nodes: list[dict] = []
    for label in TEXT_LABELS:
        value = _number(row, f"TRACE_{label}")
        if value not in (None, 0.0): nodes.append({"kind": "text", "formula": "DRAWTEXT", "text": label, "price": value})
    for name, direction, icon_id in (("TRACE_TOP1", "top", 4), ("TRACE_BOT1", "bottom", 5), ("TRACE_TOP2", "top", 2), ("TRACE_BOT2", "bottom", 1)):
        value = _number(row, name)
        if value not in (None, 0.0): nodes.append({"kind": "icon", "formula": "DRAWICON", "icon_id": icon_id, "visual": ICON_VISUALS[icon_id], "price": value, "direction": direction})
    return nodes


def _series(frame: pd.DataFrame, trace: pd.DataFrame | None = None, fallback_nodes: dict[str, list[dict]] | None = None) -> list[dict]:
    trace_by_date = {} if trace is None else {pd.Timestamp(row.date).strftime("%Y-%m-%d"): row for _, row in trace.iterrows()}
    rows = []
    for _, row in frame.iterrows():
        item: dict[str, object] = {"time": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"), "close": _number(row, "close"), "ma_120": _number(row, "EM120"), "ma_250": _number(row, "EM250"), "diff": _number(row, "MDIFF"), "dea": _number(row, "MDEA"), "macd": _number(row, "MMACD")}
        for label, red, green in EMA_PAIRS:
            red_value, green_value = _number(row, red), _number(row, green)
            key = f"ema_{label[1:]}"
            item[key] = red_value if red_value is not None else green_value
            item[f"{key}_red"] = red_value is not None
        item["draw_nodes"] = _trace_nodes(trace_by_date[item["time"]]) if item["time"] in trace_by_date else (fallback_nodes or {}).get(item["time"], _nodes(row))
        rows.append(item)
    return rows


def _calculate(symbol: str, timeframe: str, snapshot_id: str | None):
    if timeframe != "1d": raise ValueError("GPMA2_FUTU_AUTHORITY_REQUIRES_1D")
    bars, source = bars_for_source(symbol, timeframe, snapshot_id)
    code = str(source.get("code") or symbol).upper()
    result = FutuGpmaProTraceClient().calculate(bars, symbol=code, short_name=SHORT_NAME)
    closes = bars[["date", "close"]].copy(); closes["date"] = pd.to_datetime(closes["date"])
    result.frame["date"] = pd.to_datetime(result.frame["date"])
    result.frame = result.frame.merge(closes, on="date", how="left")
    return result, code, source


def _calculate_trace(symbol: str, timeframe: str, snapshot_id: str | None) -> pd.DataFrame:
    if timeframe != "1d": raise ValueError("GPMA2_FUTU_AUTHORITY_REQUIRES_1D")
    bars, source = bars_for_source(symbol, timeframe, snapshot_id)
    result = FutuGpmaProTraceClient().calculate(bars, symbol=str(source.get("code") or symbol).upper(), short_name=TRACE_SHORT_NAME)
    return result.frame


def _local_render_nodes(symbol: str, timeframe: str, snapshot_id: str | None) -> dict[str, list[dict]]:
    """Render fallback when OpenD exposes drawing primitives as zero-valued LINEs.

    Futu remains the authority for the GPMA2 GMMA lines.  This only recreates
    its final DRAWTEXT/DRAWICON coordinates from the same immutable OHLCV bars.
    """
    bars, _ = bars_for_source(symbol, timeframe, snapshot_id)
    data = GpmaAproEngine().calculate(bars)
    result: dict[str, list[dict]] = {}
    for _, row in data.iterrows():
        nodes: list[dict] = []
        for signal in SIGNALS:
            if bool(row[signal]):
                price = row.low - .5 * row.atr_26 if signal.startswith("b") else row.high + .5 * row.atr_26
                if not pd.isna(price): nodes.append({"kind": "text", "formula": "DRAWTEXT", "text": signal.upper(), "price": float(price)})
        for key, coordinate, direction, icon_id in (("top_1", "top_1_y", "top", 4), ("bottom_1", "bottom_1_y", "bottom", 5), ("top_2", "top_2_y", "top", 2), ("bottom_2", "bottom_2_y", "bottom", 1)):
            value = row.get(coordinate)
            if bool(row[key]) and not pd.isna(value): nodes.append({"kind": "icon", "formula": "DRAWICON", "icon_id": icon_id, "visual": ICON_VISUALS[icon_id], "price": float(value), "direction": direction})
        if nodes: result[pd.Timestamp(row.date).strftime("%Y-%m-%d")] = nodes
    return result


@router.get("/gpma2/{symbol}/series")
def gpma2_series(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        result, code, _ = _calculate(symbol, timeframe, snapshot_id)
        try:
            trace, trace_status = _calculate_trace(symbol, timeframe, snapshot_id), "AVAILABLE"
        except RuntimeError:
            trace, trace_status = None, "LOCAL_RENDERER_FALLBACK"
        fallback = _local_render_nodes(symbol, timeframe, snapshot_id) if trace is None else None
        return {"symbol": code, "timeframe": timeframe, "indicator": SHORT_NAME, "full_name": FULL_NAME, "script_sha256": result.script_sha256, "outputs": result.outputs, "trace_status": trace_status, "series": _series(result.frame, trace, fallback)}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except (ValueError, ImportError, RuntimeError) as error: raise HTTPException(422 if isinstance(error, ValueError) else 503, str(error))


@router.post("/gpma2/{symbol}/traces/futu")
def capture_trace(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        result, code, source = _calculate(symbol, timeframe, snapshot_id)
        return traces.import_frame(result.frame, reference="futu_opend_indicator_calc", metadata={"indicator": SHORT_NAME, "full_name": FULL_NAME, "symbol": code, "timeframe": timeframe, "source": source, "script_sha256": result.script_sha256, "outputs": result.outputs})
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except (ValueError, ImportError, RuntimeError) as error: raise HTTPException(422 if isinstance(error, ValueError) else 503, str(error))


@router.get("/gpma2/traces")
def list_traces(): return {"traces": traces.list()}


@router.get("/gpma2/{symbol}/reconciliation")
def reconciliation(symbol: str, trace_id: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        current, _, _ = _calculate(symbol, timeframe, snapshot_id)
        saved, manifest = traces.load(trace_id)
        return {"trace": manifest, "current_script_sha256": current.script_sha256, "script_changed": manifest.get("script_sha256") != current.script_sha256, "comparison": traces.compare(current.frame, saved)}
    except FileNotFoundError: raise HTTPException(404, "TRACE_OR_DATASET_NOT_FOUND")
    except (ValueError, ImportError, RuntimeError) as error: raise HTTPException(422 if isinstance(error, ValueError) else 503, str(error))
