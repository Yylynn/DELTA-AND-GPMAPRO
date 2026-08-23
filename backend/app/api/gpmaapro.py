"""Read-only GPMAAPRO v1 API; GPMAPRO remains an independent legacy endpoint."""
from fastapi import APIRouter, HTTPException
import pandas as pd

from app.api.data import bars_for_source
from app.services.gpmaapro_engine import GpmaAproEngine, SIGNALS
from app.services.gpmapro_trace import TraceSnapshotService
from app.services.futu_gpmapro_trace import FutuGpmaProTraceClient

router = APIRouter(tags=["GPMAAPRO"])
engine = GpmaAproEngine()
trace_snapshots = TraceSnapshotService(root=__import__("pathlib").Path(__file__).resolve().parents[3] / "data" / "gpmaapro_trace")


def _nodes(row: dict) -> list[dict]:
    nodes = [{"kind": "text", "formula": "DRAWTEXT", "text": key.upper(), "price": row[f"{key}_label_y"]}
             for key in SIGNALS if row.get(key) and row.get(f"{key}_label_y") is not None]
    for key, icon_id, coordinate, direction in (("top_1", 2, "top_1_y", "top"), ("bottom_1", 1, "bottom_1_y", "bottom"), ("top_2", 5, "top_2_y", "top"), ("bottom_2", 4, "bottom_2_y", "bottom")):
        if row.get(coordinate) is not None and not pd.isna(row[coordinate]):
            nodes.append({"kind": "icon", "formula": "DRAWICON", "icon_id": icon_id, "price": row[coordinate], "level": key[-1], "direction": direction})
    return nodes


@router.get("/gpmaapro/{symbol}")
def snapshot(symbol: str, timeframe: str = "1d", as_of: str | None = None, snapshot_id: str | None = None):
    try:
        data = engine.calculate(bars_for_source(symbol, timeframe, snapshot_id)[0], as_of)
        row = data.iloc[-1]
        return {"symbol": symbol.upper(), "timeframe": timeframe, "as_of": row.date.date().isoformat(),
                "signals": {key: bool(row[key]) for key in SIGNALS},
                "divergence": {key: bool(row[key]) for key in ("top_1", "bottom_1", "top_2", "bottom_2")},
                "macd": {key: None if pd.isna(row[key]) else float(row[key]) for key in ("diff", "dea", "macd", "atr_26")}}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))


@router.get("/gpmaapro/{symbol}/series")
def series(symbol: str, timeframe: str = "1d", as_of: str | None = None, snapshot_id: str | None = None):
    try:
        data = engine.calculate(bars_for_source(symbol, timeframe, snapshot_id)[0], as_of)
        columns = ["date", "close", "high", "low", "open", "atr_26", "ma_120", "ma_250", "diff", "dea", "macd", *[f"ema_{x}" for x in (8,10,12,15,20,40,45,50,55,60)], *SIGNALS, *[f"{x}_raw" for x in SIGNALS], *[f"{x}_label_y" for x in SIGNALS], "top_1", "bottom_1", "top_2", "bottom_2", "top_1_y", "bottom_1_y", "top_2_y", "bottom_2_y"]
        values = data[columns].copy().astype(object).where(pd.notna(data[columns]), None)
        values.date = data.date.dt.strftime("%Y-%m-%d")
        rows=[]
        for row in values.to_dict(orient="records"):
            time=row.pop("date"); rows.append({"time": time, **row, "draw_nodes": _nodes(row)})
        return {"symbol": symbol.upper(), "timeframe": timeframe, "series": rows}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))


@router.post("/gpmaapro/{symbol}/futu-trace")
def capture_futu_trace(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    """Ask OpenD to calculate the separately saved GPMAAPRO MAI indicator."""
    if timeframe.lower() != "1d":
        raise HTTPException(422, "FUTU_TRACE_CURRENTLY_REQUIRES_1D")
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        result = FutuGpmaProTraceClient().calculate(bars, symbol=str(source.get("code") or symbol).upper(), short_name="GPMAAPRO")
        return trace_snapshots.import_frame(result.frame, reference="futu_opend_indicator_calc", metadata={"symbol": str(source.get("code") or symbol).upper(), "timeframe": "1d", "script_sha256": result.script_sha256, "outputs": result.outputs})
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except (ImportError, RuntimeError) as error: raise HTTPException(503, str(error))


@router.get("/gpmaapro/{symbol}/reconciliation")
def reconciliation(symbol: str, trace_id: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        local = engine.calculate(bars_for_source(symbol, timeframe, snapshot_id)[0])
        trace, manifest = trace_snapshots.load(trace_id)
        return {"trace": manifest, "comparison": trace_snapshots.compare(local, trace)}
    except FileNotFoundError: raise HTTPException(404, "TRACE_OR_DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))
