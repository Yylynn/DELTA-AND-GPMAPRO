from fastapi import APIRouter, HTTPException
from app.api.data import bars_for_timeframe
from app.services.evidence_engine import EvidenceEngine

router = APIRouter(tags=["evidence"])
engine = EvidenceEngine()

@router.get("/evidence/{symbol}")
def evidence(symbol: str, timeframe: str = "1d", as_of: str | None = None):
    try:
        bars, _ = bars_for_timeframe(symbol, timeframe)
        return engine.snapshot(bars, symbol, timeframe, as_of)
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))
