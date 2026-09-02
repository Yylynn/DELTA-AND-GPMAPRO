from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.services.futu_snapshot import FutuSnapshotService
from app.services.market_snapshot import MarketSnapshotService
from app.services.research_metadata import code_identity

router = APIRouter(tags=["系统"])
started_at = datetime.now(UTC).isoformat()
futu = FutuSnapshotService()
market = MarketSnapshotService(get_settings().market_data_provider, futu=futu)

@router.get("/health")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name}
@router.get("/version")
def get_version() -> dict:
    settings = get_settings()
    return {"app": settings.app_name, "version": settings.app_version, "environment": settings.environment, **code_identity()}


@router.get("/system/status")
def system_status() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "started_at": started_at,
        "application": {"name": settings.app_name, "environment": settings.environment, **code_identity()},
        "market_data": market.status(),
        "opend": futu.connection_status(),
    }
