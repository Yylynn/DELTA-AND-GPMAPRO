from fastapi import APIRouter, HTTPException, Query
from app.api.data import bars_for_timeframe
from app.services.decision_backtest import DecisionBacktestService

router = APIRouter(tags=["decision-backtest"])

def _events(symbol: str, timeframe: str, start_date: str | None, end_date: str | None, sampling_mode: str):
    bars, _ = bars_for_timeframe(symbol, timeframe)
    return DecisionBacktestService().replay(bars, symbol, timeframe, start_date, end_date, sampling_mode)

@router.get("/backtest/decisions/{symbol}")
def summary(symbol: str, timeframe: str = "1d", start_date: str | None = None, end_date: str | None = None, sampling_mode: str = "TRANSITION"):
    try:
        events = _events(symbol, timeframe, start_date, end_date, sampling_mode)
        return DecisionBacktestService().summary(events, symbol=symbol, sampling_mode=sampling_mode, start_date=start_date, end_date=end_date)
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))

@router.get("/backtest/decisions/{symbol}/events")
def events(symbol: str, timeframe: str = "1d", start_date: str | None = None, end_date: str | None = None, sampling_mode: str = "TRANSITION", limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    try:
        all_events = _events(symbol, timeframe, start_date, end_date, sampling_mode)
        return {"total": len(all_events), "events": all_events[offset:offset + limit]}
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))

@router.get("/backtest/decisions/{symbol}/breakdown")
def breakdown(symbol: str, group_by: str, timeframe: str = "1d", start_date: str | None = None, end_date: str | None = None, sampling_mode: str = "TRANSITION"):
    try:
        return DecisionBacktestService().breakdown(_events(symbol, timeframe, start_date, end_date, sampling_mode), group_by)
    except FileNotFoundError: raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error: raise HTTPException(422, str(error))
