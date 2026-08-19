from fastapi import APIRouter, HTTPException

from app.api.data import bars_for_source
from app.services.volume_monitor import VolumeMonitor

router = APIRouter(tags=["volume"])
monitor = VolumeMonitor()


@router.get("/volume/{symbol}")
def volume(symbol: str, timeframe: str = "1d", as_of: str | None = None, snapshot_id: str | None = None):
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        return {**monitor.snapshot(bars, symbol, timeframe, as_of), "source": source}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))


@router.get("/volume/{symbol}/series")
def volume_series(symbol: str, timeframe: str = "1d", as_of: str | None = None, snapshot_id: str | None = None):
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        return {"symbol": symbol.upper(), "timeframe": timeframe, "source": source, "series": monitor.series(bars, as_of)}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))
