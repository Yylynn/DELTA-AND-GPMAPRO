from fastapi import APIRouter, HTTPException

from app.services.news_runtime import get_news_factor_service, get_news_service
from app.services.option_monitor import FutuOptionClient, OptionMonitorService, YahooOptionClient
from app.core.config import get_settings

settings = get_settings()
router = APIRouter(tags=["期权情绪雷达"])
option_client = FutuOptionClient() if settings.market_data_provider.lower() == "futu" else YahooOptionClient()
options = OptionMonitorService(client=option_client, candidate_provider=lambda limit: get_news_factor_service().candidates(limit), news_provider=lambda code: get_news_service().get(code, limit=30))

@router.get("/options/monitor")
def monitor_snapshot():
    if not settings.options_enabled:
        return {"health": {"status": "DISABLED", "source": settings.market_data_provider.upper()}, "last_check": None, "alerts": [], "unread_count": 0, "coverage": {"configured": 0, "max_per_scan": 0}}
    return options.snapshot()

@router.post("/options/monitor/check")
def monitor_check(code: str | None = None):
    if not settings.options_enabled:
        raise HTTPException(503, "期权情绪雷达当前已关闭。")
    try: return options.check(requested=code)
    except Exception as error: raise HTTPException(422, str(error))

@router.get("/options/{code}/insight")
def option_insight(code: str):
    if not settings.options_enabled:
        return {"symbol": code.upper(), "status": "NO_SNAPSHOT", "message": "期权情绪雷达当前已关闭。"}
    return options.insight(code)
