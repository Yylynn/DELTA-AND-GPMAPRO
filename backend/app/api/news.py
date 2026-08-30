from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import get_settings
from app.config.news_sources import enabled_sources, source_catalog
from app.services.news import NewsError
from app.services.news_runtime import (
    get_news_advice_service,
    get_news_evaluation_service,
    get_news_factor_service,
    get_news_research_service,
    get_news_scorecard_service,
    get_news_service,
    get_market_event_radar_service,
)

router = APIRouter(tags=["news"])
settings = get_settings()
news_service = get_news_service()
evaluation_service = get_news_evaluation_service()
factor_service = get_news_factor_service()
research_service = get_news_research_service()
advice_service = get_news_advice_service()
scorecard_service = get_news_scorecard_service()
market_event_radar_service = get_market_event_radar_service()


@router.get("/news/sources")
def news_sources():
    return {"sources": source_catalog(cnbc=settings.news_cnbc_enabled, marketwatch=settings.news_marketwatch_enabled)}


@router.get("/news/health")
def news_health():
    return {"sources": news_service.source_health()}


@router.get("/news/market")
def market_news(limit: int = 30, refresh: bool = False):
    if not settings.news_enabled:
        return {"market_items": [], "source_status": "DISABLED", "fetched_at": None, "is_cached": False, "warning": "新闻功能当前已关闭。", "source_warnings": [], "source_health": news_service.source_health()}
    try:
        return news_service.get_market(limit=limit, refresh=refresh)
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.get("/news/market/radar")
def market_event_radar(refresh: bool = False):
    if not settings.news_enabled:
        raise HTTPException(503, "新闻功能当前已关闭。")
    try:
        return market_event_radar_service.insight(refresh=refresh)
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.post("/news/factor/snapshot")
def news_factor_snapshot(refresh: bool = True):
    return factor_service.ensure_daily_snapshot(refresh=refresh)


@router.get("/news/factor/candidates")
def news_factor_candidates(limit: int = 5):
    return factor_service.candidates(limit=limit)


@router.get("/news/factor/snapshots")
def news_factor_snapshots():
    return {"snapshots": factor_service.snapshots()}


@router.get("/news/factor/evaluation")
def news_factor_evaluation():
    return evaluation_service.evaluate()


@router.get("/news/{code}/advice")
def news_advice(code: str, background_tasks: BackgroundTasks, refresh: bool = False, as_of: str | None = None):
    if not settings.news_enabled:
        raise HTTPException(503, "新闻功能当前已关闭。")
    try:
        background_tasks.add_task(factor_service.ensure_daily_snapshot, refresh=False)
        return advice_service.advice(code, refresh=refresh, as_of=as_of)
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.get("/news/{code}/scorecard")
def news_scorecard(code: str, refresh: bool = False, as_of: str | None = None):
    if not settings.news_enabled:
        raise HTTPException(503, "新闻功能当前已关闭。")
    try:
        return scorecard_service.scorecard(code, refresh=refresh, as_of=as_of)
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.get("/news/{code}/insight")
def news_insight(code: str, as_of: str | None = None):
    try:
        return news_service.insight(code, as_of=as_of)
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.get("/news/{code}/research")
def news_research(code: str, refresh: bool = False):
    if not settings.news_enabled:
        raise HTTPException(503, "新闻功能当前已关闭。")
    try:
        response = news_service.get(code, limit=100, refresh=refresh)
        payload = {"company": research_service.company_card(response), "market": research_service.market_regime(response)}
        snapshot = research_service.persist(news_service.cache_dir.parent, payload)
        return {**payload, "snapshot_id": snapshot.stem}
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.get("/news/{code}")
def news(code: str, limit: int = 20, refresh: bool = False):
    if not settings.news_enabled:
        return {"symbol": code.upper(), "provider_symbol": None, "items": [], "company_items": [], "market_items": [], "source_status": "DISABLED", "fetched_at": None, "is_cached": False, "warning": "新闻功能当前已关闭。", "dropped_unapproved_sources": [], "source_warnings": [], "source_health": news_service.source_health()}
    try:
        return news_service.get(code, limit=limit, refresh=refresh)
    except NewsError as error:
        raise HTTPException(422, str(error))
