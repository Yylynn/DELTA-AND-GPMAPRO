from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.config.news_sources import enabled_sources, source_catalog
from app.services.news import NewsError
from app.services.news_factor import NewsFactorService
from app.services.news_factor_evaluation import NewsFactorEvaluationService
from app.services.news_research import NewsResearchService
from app.services.news_runtime import get_news_service
from app.services.market_volatility_alerts import MarketVolatilityAlertService

router = APIRouter(tags=["news"])
settings = get_settings()
evaluation_service = NewsFactorEvaluationService(Path(__file__).resolve().parents[3] / "data" / "news_factor_snapshots", Path(__file__).resolve().parents[3] / "data" / "imported")
news_service = get_news_service()
factor_service = NewsFactorService(news_service, Path(__file__).resolve().parents[3] / "data" / "news_cache", evaluation_service)
research_service = NewsResearchService(news_service, MarketVolatilityAlertService())


@router.get("/news/sources")
def news_sources():
    return {"sources": source_catalog(cnbc=settings.news_cnbc_enabled, marketwatch=settings.news_marketwatch_enabled)}


@router.get("/news/health")
def news_health():
    return {"sources": news_service.source_health()}


@router.post("/news/factor/snapshot")
def news_factor_snapshot(refresh: bool = True):
    return factor_service.snapshot(refresh=refresh)


@router.get("/news/factor/candidates")
def news_factor_candidates(limit: int = 5):
    return factor_service.candidates(limit=limit)


@router.get("/news/factor/snapshots")
def news_factor_snapshots():
    return {"snapshots": factor_service.snapshots()}


@router.get("/news/factor/evaluation")
def news_factor_evaluation():
    return evaluation_service.evaluate()


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
