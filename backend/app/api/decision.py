from fastapi import APIRouter, HTTPException
from app.api.data import bars_for_timeframe
from app.services.decision_engine import DecisionEngine
from app.services.evidence_engine import EvidenceEngine

router = APIRouter(tags=["decision"])
decision_engine, evidence_engine = DecisionEngine(), EvidenceEngine()

@router.get("/decision/{symbol}")
def decision(symbol: str, timeframe: str = "1d", as_of: str | None = None):
    try:
        bars, _ = bars_for_timeframe(symbol, timeframe)
        return decision_engine.decide(evidence_engine.snapshot(bars, symbol, timeframe, as_of))
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))
