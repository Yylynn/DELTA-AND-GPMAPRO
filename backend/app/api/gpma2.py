"""Local, causal GPMA2 series with optional immutable Futu reconciliation."""
from __future__ import annotations

import hashlib
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
CALCULATION_SOURCE = "local_gpmaapro_v1"
FORMULA_PATH = Path(__file__).resolve().parents[2] / "formulas" / "GPMAAPRO_V1.mai"
EMA_PAIRS = (("E8", "E8R", "E8G"), ("E10", "E10R", "E10G"), ("E12", "E12R", "E12G"), ("E15", "E15R", "E15G"), ("E20", "E20R", "E20G"), ("E40", "E40R", "E40G"), ("E45", "E45R", "E45G"), ("E50", "E50R", "E50G"), ("E55", "E55R", "E55G"), ("E60", "E60R", "E60G"))
TEXT_LABELS = ("B01", "B02", "B03", "B11", "B12", "B3", "B4", "S01", "S02", "S11", "S12", "S2", "S22")
ICON_NODES = (("top", 4), ("bottom", 5), ("top", 2), ("bottom", 1))
ICON_VISUALS = {4: "top-face", 5: "bottom-face", 2: "top-arrow-2", 1: "bottom-arrow-2"}
traces = TraceSnapshotService(Path(__file__).resolve().parents[3] / "data" / "gpma2_trace", namespace="GPMA2")
RECONCILIATION_COLUMNS = {
    *[name for pair in EMA_PAIRS for name in pair[1:]],
    "EM120", "EM250", "MDIFF", "MDEA", "MMACD",
    *[f"TRACE_{label}" for label in TEXT_LABELS],
    "TRACE_TOP1", "TRACE_BOT1", "TRACE_TOP2", "TRACE_BOT2",
}


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
        item: dict[str, object] = {"time": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"), "close": _number(row, "close"), "atr_26": _number(row, "MATR"), "ma_120": _number(row, "EM120"), "ma_250": _number(row, "EM250"), "diff": _number(row, "MDIFF"), "dea": _number(row, "MDEA"), "macd": _number(row, "MMACD")}
        for label, red, green in EMA_PAIRS:
            red_value, green_value = _number(row, red), _number(row, green)
            key = f"ema_{label[1:]}"
            item[key] = red_value if red_value is not None else green_value
            item[f"{key}_red"] = red_value is not None
        item["draw_nodes"] = _trace_nodes(trace_by_date[item["time"]]) if item["time"] in trace_by_date else (fallback_nodes or {}).get(item["time"], _nodes(row))
        rows.append(item)
    return rows


def _calculate_futu(symbol: str, timeframe: str, snapshot_id: str | None):
    if timeframe != "1d": raise ValueError("GPMA2_REQUIRES_1D")
    bars, source = bars_for_source(symbol, timeframe, snapshot_id)
    code = str(source.get("code") or symbol).upper()
    result = FutuGpmaProTraceClient().calculate(bars, symbol=code, short_name=SHORT_NAME)
    closes = bars[["date", "close"]].copy(); closes["date"] = pd.to_datetime(closes["date"])
    result.frame["date"] = pd.to_datetime(result.frame["date"])
    result.frame = result.frame.merge(closes, on="date", how="left")
    return result, code, source


def _calculate_trace(symbol: str, timeframe: str, snapshot_id: str | None) -> pd.DataFrame:
    if timeframe != "1d": raise ValueError("GPMA2_REQUIRES_1D")
    bars, source = bars_for_source(symbol, timeframe, snapshot_id)
    result = FutuGpmaProTraceClient().calculate(bars, symbol=str(source.get("code") or symbol).upper(), short_name=TRACE_SHORT_NAME)
    return result.frame


def _local_formula_frame(data: pd.DataFrame) -> pd.DataFrame:
    """Map the reviewed Python engine to the stable Futu-shaped chart contract."""
    frame = pd.DataFrame({
        "date": data["date"], "close": data["close"], "MATR": data["atr_26"],
        "EM120": data["ma_120"], "EM250": data["ma_250"],
        "MDIFF": data["diff"], "MDEA": data["dea"], "MMACD": data["macd"],
    })
    comparison_period = {8: 10, 10: 12, 12: 15, 15: 20, 20: 15, 40: 45, 45: 50, 50: 55, 55: 60, 60: 55}
    for period, other in comparison_period.items():
        value = data[f"ema_{period}"]
        red = data[f"ema_{period}"] > data[f"ema_{other}"] if period not in {20, 60} else data[f"ema_{other}"] > data[f"ema_{period}"]
        frame[f"E{period}R"] = value.where(red)
        frame[f"E{period}G"] = value.where(~red)
    for index, signal in enumerate(SIGNALS, start=1):
        coordinate = data[f"{signal}_label_y"]
        frame[f"TRACE_{signal.upper()}"] = coordinate
        frame[f"LINE{index}"] = coordinate
    for offset, (key, coordinate, trace_name) in enumerate((("top_1", "top_1_y", "TRACE_TOP1"), ("bottom_1", "bottom_1_y", "TRACE_BOT1"), ("top_2", "top_2_y", "TRACE_TOP2"), ("bottom_2", "bottom_2_y", "TRACE_BOT2")), start=14):
        frame[trace_name] = data[coordinate]
        frame[f"LINE{offset}"] = data[coordinate]
    return frame


def _calculate_local(symbol: str, timeframe: str, snapshot_id: str | None):
    if timeframe != "1d": raise ValueError("GPMA2_REQUIRES_1D")
    bars, source = bars_for_source(symbol, timeframe, snapshot_id)
    code = str(source.get("code") or symbol).upper()
    return _local_formula_frame(GpmaAproEngine().calculate(bars)), code, source


def _script_sha256() -> str:
    return hashlib.sha256(FORMULA_PATH.read_bytes()).hexdigest()


def _comparison(local: pd.DataFrame, saved: pd.DataFrame) -> dict:
    columns = ["date", *sorted(RECONCILIATION_COLUMNS & set(local.columns) & set(saved.columns))]
    comparison = traces.compare(local[columns], saved[columns])
    comparison["required_fields"] = len(RECONCILIATION_COLUMNS)
    comparison["compared_fields"] = len(columns) - 1
    comparison["local_rows"] = len(local)
    comparison["reference_rows"] = len(saved)
    return comparison


def _comparison_status(comparison: dict) -> str:
    complete = comparison["overlap_rows"] == comparison["local_rows"] and comparison["compared_fields"] == comparison["required_fields"]
    if not complete:
        return "not_reconciled"
    return "matched" if all(field["mismatched"] == 0 for field in comparison["fields"].values()) else "drift"


def _latest_reconciliation(local: pd.DataFrame, code: str, timeframe: str) -> tuple[str, str | None]:
    for manifest in traces.list():
        if manifest.get("symbol") != code or manifest.get("timeframe") != timeframe:
            continue
        saved, _ = traces.load(manifest["trace_id"])
        return _comparison_status(_comparison(local, saved)), manifest["trace_id"]
    return "not_reconciled", None


@router.get("/gpma2/{symbol}/series")
def gpma2_series(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        frame, code, _ = _calculate_local(symbol, timeframe, snapshot_id)
        status, trace_id = _latest_reconciliation(frame, code, timeframe)
        trace_status = "AVAILABLE" if status == "matched" else "DRIFT" if status == "drift" else "LOCAL_RENDERER_FALLBACK"
        outputs = [column for column in frame.columns if column not in {"date", "close"}]
        return {"symbol": code, "timeframe": timeframe, "indicator": SHORT_NAME, "full_name": FULL_NAME, "script_sha256": _script_sha256(), "outputs": outputs, "trace_status": trace_status, "calculation_source": CALCULATION_SOURCE, "reconciliation_status": status, "reconciliation_trace_id": trace_id, "series": _series(frame, frame)}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except (ValueError, ImportError, RuntimeError) as error: raise HTTPException(422 if isinstance(error, ValueError) else 503, str(error))


@router.post("/gpma2/{symbol}/traces/futu")
def capture_trace(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        result, code, source = _calculate_futu(symbol, timeframe, snapshot_id)
        trace = _calculate_trace(symbol, timeframe, snapshot_id)
        combined = result.frame.merge(trace, on="date", how="left", suffixes=("", "_trace"))
        return traces.import_frame(combined, reference="futu_opend_indicator_calc", metadata={"indicator": SHORT_NAME, "full_name": FULL_NAME, "symbol": code, "timeframe": timeframe, "source": source, "script_sha256": result.script_sha256, "outputs": list(combined.columns)})
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except (ValueError, ImportError, RuntimeError) as error: raise HTTPException(422 if isinstance(error, ValueError) else 503, str(error))


@router.get("/gpma2/traces")
def list_traces(): return {"traces": traces.list()}


@router.get("/gpma2/{symbol}/reconciliation")
def reconciliation(symbol: str, trace_id: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        current, code, _ = _calculate_local(symbol, timeframe, snapshot_id)
        saved, manifest = traces.load(trace_id)
        if manifest.get("symbol") != code or manifest.get("timeframe") != timeframe:
            raise ValueError("trace does not match requested symbol and timeframe")
        comparison = _comparison(current, saved)
        return {"trace": manifest, "calculation_source": CALCULATION_SOURCE, "current_script_sha256": _script_sha256(), "reference_script_sha256": manifest.get("script_sha256"), "reconciliation_status": _comparison_status(comparison), "comparison": comparison}
    except FileNotFoundError: raise HTTPException(404, "TRACE_OR_DATASET_NOT_FOUND")
    except (ValueError, ImportError, RuntimeError) as error: raise HTTPException(422 if isinstance(error, ValueError) else 503, str(error))
