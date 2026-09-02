import re
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.data.providers import CsvDataProvider
from app.services.data_freshness import freshness_snapshot
from app.services.batch_import import import_batch
from app.services.dataset import RESEARCH_BASKET, coverage, snapshot, universe
from app.services.futu_snapshot import FutuOpenDError, FutuSnapshotService
from app.services.market_snapshot import MarketDataError, MarketSnapshotService
from app.core.config import get_settings
from app.api.delta import load as load_delta_events

router = APIRouter(tags=["data"])
provider = CsvDataProvider(Path(__file__).resolve().parents[3] / "data" / "imported")
futu_snapshots = FutuSnapshotService()
market_snapshots = MarketSnapshotService(get_settings().market_data_provider, futu=futu_snapshots)


def bars_for_timeframe(symbol: str, timeframe: str = "1d"):
    df, quality = provider.ohlcv(symbol)
    if timeframe == "1d": return df, quality
    if timeframe not in {"1w", "1mo"}: raise ValueError("timeframe must be 1d, 1w or 1mo")
    data = df.copy(); data["date"] = pd.to_datetime(data["date"]); data = data.set_index("date")
    rule = "W-FRI" if timeframe == "1w" else "ME"
    aggregated = data.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    # Resample labels such as month-end can lie in the future while the
    # current period is still open.  Use the final actual trading bar instead.
    last_dates = data["close"].resample(rule).apply(lambda values: values.index[-1]).reset_index(drop=True)
    aggregated["date"] = pd.to_datetime(last_dates).dt.strftime("%Y-%m-%d")
    return aggregated, {**quality, "bar_count": len(aggregated), "timeframe": timeframe}


def _futu_code(symbol: str) -> str:
    value = symbol.strip().upper()
    return value if "." in value else f"US.{value}"


def _bars_from_snapshot(df: pd.DataFrame, quality: dict, timeframe: str):
    if quality.get("timeframe") == timeframe:
        return df, quality
    if quality.get("timeframe") != "1d" or timeframe not in {"1w", "1mo"}:
        raise ValueError("snapshot timeframe does not match request")
    data = df.copy(); data["date"] = pd.to_datetime(data["date"]); data = data.set_index("date")
    rule = "W-FRI" if timeframe == "1w" else "ME"
    result = data.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    last_dates = data["close"].resample(rule).apply(lambda values: values.index[-1]).reset_index(drop=True)
    result["date"] = pd.to_datetime(last_dates).dt.strftime("%Y-%m-%d")
    return result, {**quality, "timeframe": timeframe, "bar_count": len(result), "resampled_from": "1d"}


def bars_for_source(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    # The GPMAPRO reconciliation authority is US.AAPL / daily / QFQ.  When a
    # snapshot is available, make it the default source for this one benchmark
    # instead of silently falling back to the unrelated imported CSV.
    if snapshot_id is None and symbol.upper() == "AAPL" and timeframe == "1d":
        candidates = [
            item for item in market_snapshots.list()
            if item.get("code") == "US.AAPL" and item.get("timeframe") == "1d" and item.get("autype") == "QFQ"
        ]
        if candidates:
            snapshot_id = candidates[0]["snapshot_id"]
    if snapshot_id:
        df, quality = market_snapshots.load(snapshot_id)
        if quality["code"] != _futu_code(symbol):
            raise ValueError("snapshot code does not match requested symbol")
        return _bars_from_snapshot(df, quality, timeframe)
    return bars_for_timeframe(symbol, timeframe)


class MarketSnapshotRequest(BaseModel):
    code: str = "US.VXN"
    timeframe: str = "1d"
    adjustment: str = "adjusted"
    start: str = "2018-01-01"
    end: str | None = None


class MarketBatchSnapshotRequest(BaseModel):
    codes: list[str] = list(f"US.{symbol}" for symbol in RESEARCH_BASKET)
    timeframe: str = "1d"
    adjustment: str = "adjusted"
    start: str = "2010-01-01"
    end: str | None = None


@router.get("/data/market/status")
def market_status():
    return market_snapshots.status()


@router.get("/data/market/snapshots")
def list_market_snapshots():
    return {"provider": market_snapshots.provider_name, "snapshots": market_snapshots.list()}


@router.post("/data/market/snapshots")
def fetch_market_snapshot(request: MarketSnapshotRequest):
    try:
        return market_snapshots.fetch_history_snapshot(
            request.code, request.timeframe, request.adjustment, request.start, request.end,
        )
    except (MarketDataError, FutuOpenDError, ValueError) as error:
        raise HTTPException(503 if isinstance(error, (MarketDataError, FutuOpenDError)) else 422, str(error))


@router.post("/data/market/snapshots/batch")
def fetch_market_snapshot_batch(request: MarketBatchSnapshotRequest):
    created, failed = [], []
    for raw_code in dict.fromkeys(request.codes):
        try:
            created.append(market_snapshots.fetch_history_snapshot(
                raw_code, request.timeframe, request.adjustment, request.start, request.end,
            ))
        except (MarketDataError, FutuOpenDError, ValueError) as error:
            failed.append({"code": raw_code, "error": str(error)})
    return {"provider": market_snapshots.provider_name, "requested": len(set(request.codes)), "created": created, "failed": failed}


def _research_coverage(items: list[dict]) -> dict:
    latest: dict[str, dict] = {}
    for item in items:
        if item.get("timeframe") != "1d" or item.get("autype") != "QFQ":
            continue
        latest.setdefault(item.get("code", ""), item)
    rows = []
    for symbol, category in RESEARCH_BASKET.items():
        item = latest.get(f"US.{symbol}")
        bars = int(item.get("bar_count", 0)) if item else 0
        rows.append({"symbol": symbol, "code": f"US.{symbol}", "category": category, "snapshot_id": item.get("snapshot_id") if item else None, "provider": item.get("provider", "futu") if item else None, "bars": bars, "start_date": item.get("start_date") if item else None, "end_date": item.get("end_date") if item else None, "fetched_at": item.get("fetched_at") if item else None, "freshness": freshness_snapshot(str(item.get("end_date")), bars)["freshness"] if item else "UNKNOWN", "research_eligibility": "ELIGIBLE" if bars >= 750 else "LIMITED" if bars >= 250 else "INELIGIBLE"})
    eligible = sum(row["research_eligibility"] == "ELIGIBLE" for row in rows)
    return {"provider": market_snapshots.provider_name, "eligible_symbols": eligible, "required_symbols": len(RESEARCH_BASKET), "status": "READY" if eligible == len(RESEARCH_BASKET) else "NOT_READY", "symbols": rows}


@router.get("/data/market/coverage")
def market_research_coverage():
    return _research_coverage(market_snapshots.list())


@router.get("/data/market/snapshots/{snapshot_id}/ohlcv")
def market_snapshot_ohlcv(snapshot_id: str, timeframe: str = "1d"):
    try:
        frame, manifest = market_snapshots.load(snapshot_id)
        df, quality = _bars_from_snapshot(frame, manifest, timeframe)
        return {"snapshot": quality, "bars": df.to_dict(orient="records")}
    except FileNotFoundError:
        raise HTTPException(404, "MARKET_SNAPSHOT_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.get("/data/futu/snapshots")
def list_futu_snapshots():
    return {"snapshots": futu_snapshots.list()}


@router.get("/data/futu/quota")
def futu_quota():
    try:
        return futu_snapshots.quota()
    except FutuOpenDError as error:
        raise HTTPException(503, str(error))


class FutuSnapshotRequest(BaseModel):
    code: str = "US.VXN"
    timeframe: str = "1d"
    autype: str = "QFQ"
    start: str = "2018-01-01"
    end: str | None = None


@router.post("/data/futu/snapshots")
def fetch_futu_snapshot(request: FutuSnapshotRequest):
    try:
        return futu_snapshots.fetch_history_snapshot(
            code=request.code, timeframe=request.timeframe, autype=request.autype,
            start=request.start, end=request.end,
        )
    except (FutuOpenDError, ValueError) as error:
        raise HTTPException(503 if isinstance(error, FutuOpenDError) else 422, str(error))


class FutuBatchSnapshotRequest(BaseModel):
    codes: list[str] = list(f"US.{symbol}" for symbol in RESEARCH_BASKET)
    timeframe: str = "1d"
    autype: str = "QFQ"
    start: str = "2010-01-01"
    end: str | None = None


@router.post("/data/futu/snapshots/batch")
def fetch_futu_snapshot_batch(request: FutuBatchSnapshotRequest):
    """Create one immutable OpenD snapshot per requested research symbol.

    A failed symbol does not invalidate snapshots already captured for the rest
    of the basket; the response makes the partial outcome explicit.
    """
    created, failed = [], []
    for raw_code in dict.fromkeys(request.codes):
        try:
            created.append(futu_snapshots.fetch_history_snapshot(raw_code, request.timeframe, request.autype, request.start, request.end))
        except (FutuOpenDError, ValueError) as error:
            failed.append({"code": raw_code, "error": str(error)})
    return {"requested": len(set(request.codes)), "created": created, "failed": failed}


@router.get("/data/futu/research-coverage")
def futu_research_coverage():
    return _research_coverage(futu_snapshots.list())


@router.post("/data/futu/snapshots/aapl-qfq")
def fetch_aapl_qfq_snapshot():
    try:
        return futu_snapshots.fetch_daily_qfq()
    except (FutuOpenDError, ValueError) as error:
        raise HTTPException(503, str(error))


@router.get("/data/futu/snapshots/{snapshot_id}/ohlcv")
def futu_snapshot_ohlcv(snapshot_id: str, timeframe: str = "1d"):
    try:
        frame, manifest = futu_snapshots.load(snapshot_id)
        # Always pass snapshots through the same timeframe conversion used by
        # GPMAPRO, DELTA and volume.  Returning raw daily bars here while the
        # other layers use weekly/monthly bars breaks the shared time scale.
        df, quality = _bars_from_snapshot(frame, manifest, timeframe)
        return {"snapshot": quality, "bars": df.to_dict(orient="records")}
    except FileNotFoundError:
        raise HTTPException(404, "FUTU_SNAPSHOT_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/data/import")
async def import_csv(symbol: str = Form(...), file: UploadFile = File(...)):
    if not symbol.strip(): raise HTTPException(422, "symbol must not be empty")
    if not file.filename or not file.filename.lower().endswith(".csv"): raise HTTPException(422, "CSV file required")
    try:
        data, quality = provider.save(symbol, await file.read())
        freshness = freshness_snapshot(str(data.date.iloc[-1]), len(data))
        return {"symbol": symbol.upper(), "rows_imported": quality["bar_count"], **quality, **freshness}
    except ValueError as error: raise HTTPException(422, str(error))


@router.post("/market-data/import-csv")
async def import_market_csv(file: Annotated[UploadFile, File(...)], symbol: Annotated[str | None, Form()] = None):
    filename = file.filename or ""; derived = re.sub(r"[^A-Za-z0-9._-]", "_", (symbol or Path(filename).stem).upper())
    if not derived: raise HTTPException(422, "could not derive symbol")
    if not filename.lower().endswith(".csv"): raise HTTPException(422, "CSV file required")
    try:
        df, quality = provider.save(derived, await file.read())
        freshness = freshness_snapshot(str(df.date.iloc[-1]), len(df))
        return {"success": True, "dataset_id": derived, "filename": filename, "rows": quality["bar_count"], **quality, **freshness, "first_close": float(df.close.iloc[0]), "last_close": float(df.close.iloc[-1])}
    except ValueError as error: raise HTTPException(422, str(error))


@router.post("/data/import/batch")
async def import_csv_batch(files: list[UploadFile] = File(...)):
    return import_batch(provider, [(file.filename or "", await file.read()) for file in files])


@router.get("/data/symbols")
def symbols(): return {"symbols": universe(provider)}


@router.get("/data/coverage")
def data_coverage(): return coverage(provider)


@router.get("/data/snapshot")
def dataset_snapshot(): return snapshot(provider, load_delta_events())


@router.get("/data/{symbol}/ohlcv")
def ohlcv(symbol: str, timeframe: str = "1d"):
    try:
        df, _ = bars_for_timeframe(symbol, timeframe); return {"symbol": symbol.upper(), "timeframe": timeframe, "bars": df.to_dict(orient="records")}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))


@router.get("/data/{symbol}/quality")
def quality(symbol: str):
    try:
        _, report = provider.ohlcv(symbol); return {"symbol": symbol.upper(), "source": "local CSV", **report}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
