"""Independent API surface for the research-only stock-pool workspace."""
from pathlib import Path

from fastapi import APIRouter

from app.services.market_volatility_alerts import MarketVolatilityAlertService
from app.services.news_runtime import get_news_service
from app.services.stock_pool import StockPoolService

router = APIRouter(tags=["stock-pool"])
service = StockPoolService(
    Path(__file__).resolve().parents[3] / "data" / "stock_pool_snapshots",
    news_service=get_news_service(), market_alerts=MarketVolatilityAlertService(),
)


@router.get("/stock-pool")
def latest():
    return service.latest()


@router.get("/stock-pool/latest")
def latest_snapshot():
    return service.latest()


@router.post("/stock-pool/scan")
def scan():
    # Manual refresh intentionally follows the same post-close guard as the
    # scheduler, so an intraday partial daily bar cannot become a daily record.
    return service.ensure_daily_scan()


@router.get("/stock-pool/snapshots")
def snapshots():
    return {"snapshots": service.snapshots()}


@router.get("/stock-pool/universe")
def universe():
    return service.universe()


@router.get("/stock-pool/health")
def health():
    return service.health()


@router.get("/stock-pool/config")
def config():
    return service.config()


@router.get("/stock-pool/evaluation")
def evaluation():
    return service.evaluation()
