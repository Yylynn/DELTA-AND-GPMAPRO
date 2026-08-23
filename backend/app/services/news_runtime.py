"""Single configured news-service instance shared by all research surfaces."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config.news_sources import enabled_sources
from app.core.config import get_settings
from app.services.news import NewsService


@lru_cache
def get_news_service() -> NewsService:
    settings = get_settings()
    return NewsService(
        Path(__file__).resolve().parents[3] / "data" / "news_cache",
        ttl_seconds=settings.news_cache_ttl_seconds,
        sources=enabled_sources(cnbc=settings.news_cnbc_enabled, marketwatch=settings.news_marketwatch_enabled),
        rss_timeout_seconds=settings.news_rss_timeout_seconds,
        finnhub_api_key=settings.finnhub_api_key,
        sec_user_agent=settings.sec_user_agent,
    )
