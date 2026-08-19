from fastapi import APIRouter

from app.api.event_backtest import event_backtest
from app.services.event_analytics import EventAnalyticsService

router = APIRouter(tags=["event-analytics"])


@router.get("/backtest/analytics/{symbol}")
def event_analytics(symbol: str, timeframe: str = "1d", start_date: str | None = None, end_date: str | None = None):
    backtest = event_backtest(symbol, timeframe, start_date, end_date)
    return {"symbol": symbol.upper(), "timeframe": timeframe, "date_range": backtest["date_range"], "event_count": len(backtest["event_results"]), **EventAnalyticsService().analyze(backtest["event_results"])}
