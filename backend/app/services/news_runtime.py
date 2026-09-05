"""Single configured news-service instance shared by all research surfaces."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config.news_sources import enabled_sources
from app.core.config import get_settings
from app.services.market_volatility_alerts import MarketVolatilityAlertService
from app.services.news import NewsService
from app.services.news_advice import NewsAdviceService
from app.services.news_factor import NewsFactorService
from app.services.news_factor_evaluation import NewsFactorEvaluationService
from app.services.news_research import NewsResearchService
from app.services.market_event_radar import MarketEventRadarService
from app.services.news_scorecard import NewsImpactScorecardService
from app.services.news_translation import HeadlineTranslator


DATA_ROOT = Path(__file__).resolve().parents[3] / "data"


@lru_cache
def get_news_service() -> NewsService:
    settings = get_settings()
    return NewsService(
        DATA_ROOT / "news_cache",
        ttl_seconds=settings.news_cache_ttl_seconds,
        sources=enabled_sources(cnbc=settings.news_cnbc_enabled, marketwatch=settings.news_marketwatch_enabled),
        rss_timeout_seconds=settings.news_rss_timeout_seconds,
        finnhub_api_key=settings.finnhub_api_key,
        sec_user_agent=settings.sec_user_agent,
        zh_sentiment_enabled=settings.news_zh_sentiment_enabled,
    )


@lru_cache
def get_news_evaluation_service() -> NewsFactorEvaluationService:
    return NewsFactorEvaluationService(DATA_ROOT / "news_factor_snapshots", DATA_ROOT / "imported")


@lru_cache
def get_news_research_service() -> NewsResearchService:
    return NewsResearchService(get_news_service(), MarketVolatilityAlertService())


@lru_cache
def get_news_factor_service() -> NewsFactorService:
    return NewsFactorService(get_news_service(), DATA_ROOT / "news_cache", get_news_evaluation_service())


@lru_cache
def get_news_advice_service() -> NewsAdviceService:
    return NewsAdviceService(get_news_service(), get_news_evaluation_service(), get_news_research_service(), DATA_ROOT / "news_factor_snapshots")


@lru_cache
def get_news_scorecard_service() -> NewsImpactScorecardService:
    return NewsImpactScorecardService(get_news_service(), get_news_advice_service(), get_news_evaluation_service(), DATA_ROOT / "imported")


@lru_cache
def get_market_event_radar_service() -> MarketEventRadarService:
    return MarketEventRadarService(
        get_news_service(),
        MarketVolatilityAlertService(),
        DATA_ROOT,
        HeadlineTranslator(DATA_ROOT / "news_cache" / "headline_translations_zh.json"),
    )
