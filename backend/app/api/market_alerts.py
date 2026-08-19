from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.market_volatility_alerts import MarketVolatilityAlertService

router = APIRouter(tags=["市场波动率预警"])
alerts = MarketVolatilityAlertService()

class AlertConfigRequest(BaseModel):
    change_threshold_pct: float = 3.0
    indicators: list[dict]

@router.get("/market-volatility-alerts")
def snapshot(): return alerts.snapshot()

@router.put("/market-volatility-alerts/config")
def update_config(request: AlertConfigRequest):
    try: return alerts.update_config(request.model_dump())
    except ValueError as error: raise HTTPException(422, str(error))

@router.post("/market-volatility-alerts/check")
def check(): return alerts.check()

@router.post("/market-volatility-alerts/read")
def mark_read(): return alerts.mark_read()
