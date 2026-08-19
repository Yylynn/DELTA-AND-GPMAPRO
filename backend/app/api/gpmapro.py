from fastapi import APIRouter, File, HTTPException, UploadFile
import pandas as pd

from app.api.data import bars_for_source
from app.services.gpmapro_engine import GpmaProEngine
from app.services.gpmapro_trace import TraceSnapshotService
from app.services.futu_gpmapro_trace import FutuGpmaProTraceClient

router = APIRouter(tags=["GPMAPRO"])
engine = GpmaProEngine()
trace_snapshots = TraceSnapshotService()


def _draw_nodes(row: dict) -> list[dict]:
    """The final MaiLanguage drawing statements, in price coordinates."""
    nodes: list[dict] = []
    for key, text, coordinate in (("b1", "B1", "b1_label_y"), ("b2", "B2", "b2_label_y"), ("b3", "B3", "b3_label_y"), ("s1", "S1", "s1_label_y"), ("s2", "S2", "s2_label_y")):
        if row.get(key) and row.get(coordinate) is not None:
            nodes.append({"kind": "text", "formula": "DRAWTEXT", "text": text, "price": row[coordinate]})
    for key, icon_id, coordinate, level, direction in (("top_face", 6, "top_face_y", 1, "top"), ("bottom_face", 5, "bottom_face_y", 1, "bottom"), ("top_2", 2, "top_arrow_2_y", 2, "top"), ("bottom_2", 1, "bottom_arrow_2_y", 2, "bottom"), ("top_3", 26, "top_arrow_3_y", 3, "top"), ("bottom_3", 25, "bottom_arrow_3_y", 3, "bottom")):
        if row.get(key) and row.get(coordinate) is not None:
            nodes.append({"kind": "icon", "formula": "DRAWICON", "icon_id": icon_id, "price": row[coordinate], "level": level, "direction": direction})
    return nodes


TRACE_COLUMNS = [
    "E8", "E10", "E12", "E15", "E20", "E40", "E45", "E50", "E55", "E60", "E120", "E250",
    "DIFF", "DEA", "MACD", "ATR", "JC", "SC", "N1", "N2", "HH", "MHD", "LL", "MLD", "PP", "MMH", "TT", "MML",
    "TBL10", "BBL10", "TBL20", "BBL20", "TBL30", "BBL30", "TBL1", "BBL1", "TBL2", "BBL2", "TBL3", "BBL3",
]


@router.get("/gpmapro/traces")
def list_gpmapro_traces():
    return {"traces": trace_snapshots.list()}


@router.post("/gpmapro/traces/import")
async def import_gpmapro_trace(file: UploadFile = File(...), reference: str = "futu_desktop_export"):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(422, "TRACE_IMPORT_REQUIRES_CSV")
    try:
        frame = pd.read_csv(file.file)
        return trace_snapshots.import_frame(frame, reference=reference)
    except (ValueError, pd.errors.ParserError) as error:
        raise HTTPException(422, str(error))


@router.post("/gpmapro/traces/futu/{symbol}")
def capture_futu_gpmapro_trace(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    """Create an immutable OpenD-calculated TRACE snapshot from an existing OHLCV snapshot."""
    if timeframe.lower() != "1d":
        raise HTTPException(422, "FUTU_TRACE_CURRENTLY_REQUIRES_1D")
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        # The trace clone contains the authority formula unchanged plus
        # numeric NODRAW outputs for every final DRAWTEXT/DRAWICON clause.
        market_code = str(source.get("code") or symbol).upper()
        result = FutuGpmaProTraceClient().calculate(bars, symbol=market_code, short_name="GPMAPRO_TRACE")
        manifest = trace_snapshots.import_frame(
            result.frame,
            reference="futu_opend_indicator_calc",
            metadata={"symbol": market_code, "timeframe": "1d", "source": source,
                      "trace_short_name": "GPMAPRO_TRACE",
                      "parent_script_sha256": "3a11a5f2252df502f20c95c231b07090d2fcf06a42b2986d83106ce535d2b664",
                      "trace_script_sha256": result.script_sha256, "outputs": result.outputs},
        )
        return manifest
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except (ImportError, RuntimeError) as error:
        raise HTTPException(503, str(error))


@router.get("/gpmapro/{symbol}/trace")
def gpmapro_trace(symbol: str, date: str, timeframe: str = "1d", snapshot_id: str | None = None):
    """Return the actual named MaiLanguage primitives for one daily bar."""
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        data = engine.calculate(bars, as_of=date)
        row = data.iloc[-1]
        if row.date.strftime("%Y-%m-%d") != date:
            raise ValueError("No OHLCV bar exists on this date")
        values = {name: (None if pd.isna(row[name]) else bool(row[name]) if isinstance(row[name], bool) else float(row[name])) for name in TRACE_COLUMNS if name in data.columns}
        return {"source": source, "date": date, "values": values, "draw_nodes": _draw_nodes(row.to_dict())}
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get("/gpmapro/{symbol}/reconciliation")
def reconcile_gpmapro_trace(symbol: str, trace_id: str, timeframe: str = "1d", snapshot_id: str | None = None):
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        local = engine.calculate(bars)
        trace, manifest = trace_snapshots.load(trace_id)
        return {"source": source, "trace": manifest, "comparison": trace_snapshots.compare(local, trace)}
    except FileNotFoundError:
        raise HTTPException(404, "TRACE_OR_DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get("/gpmapro/{symbol}/diagnostics")
def gpmapro_diagnostics(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    """Explain every visible formula node without exposing a trading action."""
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        data = engine.calculate(bars)
        labels = ["b1", "b2", "b3", "s1", "s2", "top_face", "bottom_face", "top_2", "bottom_2", "top_3", "bottom_3"]
        rows = data.loc[data[labels].any(axis=1), ["date", "open", "high", "low", "close", "atr_26", *labels, "top_1_raw", "bottom_1_raw", "top_2_raw", "bottom_2_raw", "top_3_raw", "bottom_3_raw", *[name for name in TRACE_COLUMNS if name in data]]].copy()
        rows["date"] = rows["date"].dt.strftime("%Y-%m-%d")
        return {"source": source, "rows": rows.tail(100).replace({pd.NA: None, float("nan"): None}).to_dict(orient="records")}
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get("/gpmapro/{symbol}")
def gpmapro(symbol: str, timeframe: str = "1d", as_of: str | None = None, snapshot_id: str | None = None):
    try:
        bars, _ = bars_for_source(symbol, timeframe, snapshot_id)
        return engine.snapshot(bars, symbol, timeframe, as_of)
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get("/gpmapro/{symbol}/series")
def gpmapro_series(symbol: str, timeframe: str = "1d", as_of: str | None = None, snapshot_id: str | None = None):
    try:
        bars, _ = bars_for_source(symbol, timeframe, snapshot_id)
        data = engine.calculate(bars, as_of)
        # Keep the full calculation contract available to the research UI.  The
        # final B/S signals and raw divergence warnings remain separate so a
        # chart never presents an unfiltered formula condition as an action.
        columns = ["date", "close", "atr_26", "ma_120", "ma_250", "diff", "dea", "macd", "volume", "vol_ma_20", "volume_ratio", "gap_rate", "ema_8", "ema_10", "ema_12", "ema_15", "ema_20", "ema_40", "ema_45", "ema_50", "ema_55", "ema_60", "bull_bg", "bull_strong", "bear_bg", "vol_ok", "vol_strong", "gap_ok", "range_ok", "top_confirm", "bottom_confirm", "buy_ok", "buy_strong_ok", "sell_ok", "b1_raw", "b2_raw", "b3_raw", "s1_raw", "s2_raw", "b1", "b2", "b3", "s1", "s2", "top_1_raw", "top_2_raw", "top_3_raw", "bottom_1_raw", "bottom_2_raw", "bottom_3_raw", "ema_8_red", "ema_10_red", "ema_12_red", "ema_15_red", "ema_20_red", "ema_40_red", "ema_45_red", "ema_50_red", "ema_55_red", "ema_60_red", "b1_label_y", "b2_label_y", "b3_label_y", "s1_label_y", "s2_label_y", "top_1", "top_2", "top_3", "bottom_1", "bottom_2", "bottom_3", "top_face", "bottom_face", "top_face_y", "bottom_face_y", "top_arrow_2_y", "bottom_arrow_2_y", "top_arrow_3_y", "bottom_arrow_3_y"]
        values = data[columns].copy().astype(object).where(pd.notna(data[columns]), None)
        values["date"] = data["date"].dt.strftime("%Y-%m-%d")
        series = []
        for row in values.to_dict(orient="records"):
            time = row.pop("date")
            series.append({"time": time, **row, "draw_nodes": _draw_nodes(row)})
        return {"symbol": symbol.upper(), "timeframe": timeframe, "series": series}
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))
