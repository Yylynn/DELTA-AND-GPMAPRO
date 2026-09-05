import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.system import router as system_router
from app.api.data import router as data_router
from app.api.delta import router as delta_router
from app.api.gpmapro import router as gpmapro_router
from app.api.gpmaapro import router as gpmaapro_router
from app.api.gpma2 import router as gpma2_router
from app.api.interpretation import router as interpretation_router
from app.api.volume import router as volume_router
from app.api.itd import router as itd_router
from app.api.event_backtest import router as event_backtest_router
from app.api.event_analytics import router as event_analytics_router
from app.api.evidence import router as evidence_router
from app.api.decision import router as decision_router
from app.api.decision_backtest import router as decision_backtest_router
from app.api.decision_diagnostics import router as decision_diagnostics_router
from app.api.signal_backtest import router as signal_backtest_router
from app.api.portfolio_backtest import router as portfolio_backtest_router
from app.api.walk_forward import router as walk_forward_router
from app.api.strategy_lab import router as strategy_lab_router
from app.api.signal_rules import router as signal_rules_router
from app.api.backtest_datasets import router as backtest_datasets_router
from app.api.market_alerts import router as market_alerts_router
from app.api.news import router as news_router
from app.api.options import router as options_router
from app.api.options import options as option_monitor
from app.api.stock_pool import router as stock_pool_router
from app.api.stock_pool import service as stock_pool_service
from app.api.chanlun import router as chanlun_router
from app.core.config import get_settings
from app.services.news_runtime import get_news_service
settings = get_settings()
market_news_service = get_news_service()

async def _option_monitor_loop():
    while True:
        try:
            if settings.options_enabled:
                await asyncio.to_thread(option_monitor.check, force=False)
        except Exception:
            # API health exposes failures; a transient OpenD outage must not
            # bring down the research terminal or the news pipeline.
            pass
        await asyncio.sleep(300)

async def _stock_pool_loop():
    while True:
        try:
            if settings.stock_pool_enabled:
                await asyncio.to_thread(stock_pool_service.ensure_daily_scan)
        except Exception:
            # The stock pool is a separate research surface.  A missing local
            # data file or temporary news outage must never stop the terminal.
            pass
        await asyncio.sleep(300)

async def _market_news_loop():
    """Refresh publisher RSS metadata immediately and every fifteen minutes."""
    while True:
        try:
            if settings.news_enabled:
                await asyncio.to_thread(market_news_service.get_market, limit=100, refresh=True)
        except Exception:
            # The service keeps the last successful cache for degraded reads.
            pass
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_option_monitor_loop())
    stock_pool_task = asyncio.create_task(_stock_pool_loop())
    market_news_task = asyncio.create_task(_market_news_loop())
    try:
        yield
    finally:
        task.cancel()
        stock_pool_task.cancel()
        market_news_task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(asyncio.CancelledError):
            await stock_pool_task
        with suppress(asyncio.CancelledError):
            await market_news_task

app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(system_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(delta_router, prefix="/api")
app.include_router(gpmapro_router, prefix="/api")
app.include_router(gpmaapro_router, prefix="/api")
app.include_router(gpma2_router, prefix="/api")
app.include_router(interpretation_router, prefix="/api")
app.include_router(volume_router, prefix="/api")
app.include_router(itd_router, prefix="/api")
app.include_router(chanlun_router, prefix="/api")
app.include_router(event_backtest_router, prefix="/api")
app.include_router(event_analytics_router, prefix="/api")
app.include_router(evidence_router, prefix="/api")
app.include_router(decision_router, prefix="/api")
app.include_router(decision_backtest_router, prefix="/api")
app.include_router(decision_diagnostics_router, prefix="/api")
app.include_router(signal_backtest_router, prefix="/api")
app.include_router(portfolio_backtest_router, prefix="/api")
app.include_router(walk_forward_router, prefix="/api")
app.include_router(strategy_lab_router, prefix="/api")
app.include_router(signal_rules_router, prefix="/api")
app.include_router(backtest_datasets_router, prefix="/api")
app.include_router(market_alerts_router, prefix="/api")
app.include_router(news_router, prefix="/api")
app.include_router(options_router, prefix="/api")
app.include_router(stock_pool_router, prefix="/api")
