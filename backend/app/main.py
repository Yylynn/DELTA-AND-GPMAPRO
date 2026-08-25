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
from app.api.backtest_datasets import router as backtest_datasets_router
from app.api.market_alerts import router as market_alerts_router
from app.api.news import router as news_router
from app.core.config import get_settings
settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
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
app.include_router(backtest_datasets_router, prefix="/api")
app.include_router(market_alerts_router, prefix="/api")
app.include_router(news_router, prefix="/api")
