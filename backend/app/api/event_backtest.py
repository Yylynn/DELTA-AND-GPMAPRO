from fastapi import APIRouter, HTTPException

from app.api.data import bars_for_timeframe
from app.services.event_backtest import EventBacktestService

router = APIRouter(tags=["event-backtest"])


@router.get("/backtest/events/{symbol}")
def event_backtest(symbol: str, timeframe: str = "1d", start_date: str | None = None, end_date: str | None = None):
    try:
        bars, _ = bars_for_timeframe(symbol, timeframe)
        result = EventBacktestService().run(bars, start_date=start_date, end_date=end_date)
        return {"symbol": symbol.upper(), "timeframe": timeframe, "date_range": {"start": start_date, "end": end_date}, **result}
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))
