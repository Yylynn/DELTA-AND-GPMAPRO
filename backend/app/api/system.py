from fastapi import APIRouter
from app.core.config import get_settings
router = APIRouter(tags=["系统"])
@router.get("/health")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name}
@router.get("/version")
def get_version() -> dict[str, str]:
    settings = get_settings()
    return {"app": settings.app_name, "version": settings.app_version, "environment": settings.environment}
