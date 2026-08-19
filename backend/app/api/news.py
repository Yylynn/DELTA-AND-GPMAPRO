from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.config.news_sources import enabled_sources, source_catalog
from app.services.news import NewsError, NewsService

router = APIRouter(tags=["news"])
settings = get_settings()
news_service = NewsService(
    Path(__file__).resolve().parents[3] / "data" / "news_cache",
    ttl_seconds=settings.news_cache_ttl_seconds,
    sources=enabled_sources(cnbc=settings.news_cnbc_enabled, marketwatch=settings.news_marketwatch_enabled),
    rss_timeout_seconds=settings.news_rss_timeout_seconds,
)


@router.get("/news/sources")
def news_sources():
    return {"sources": source_catalog(cnbc=settings.news_cnbc_enabled, marketwatch=settings.news_marketwatch_enabled)}


@router.get("/news/{code}/insight")
def news_insight(code: str, as_of: str | None = None):
    try:
        return news_service.insight(code, as_of=as_of)
    except NewsError as error:
        raise HTTPException(422, str(error))


@router.get("/news/{code}")
def news(code: str, limit: int = 20, refresh: bool = False):
    if not settings.news_enabled:
        return {"symbol": code.upper(), "items": [], "source_status": "DISABLED", "fetched_at": None, "is_cached": False, "warning": "新闻功能当前已关闭。"}
    try:
        return news_service.get(code, limit=limit, refresh=refresh)
    except NewsError as error:
        raise HTTPException(422, str(error))
