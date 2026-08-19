from fastapi import APIRouter, HTTPException
from app.api.data import bars_for_timeframe
from app.models.decision_diagnostics import DiagnosticsRequest
from app.services.decision_diagnostics import DecisionDiagnostics
from app.api.data import provider
from app.services.dataset import universe
from app.services.readiness import readiness
router = APIRouter(tags=["decision-diagnostics"])
@router.post("/diagnostics/decisions")
def diagnostics(request: DiagnosticsRequest):
    try:
        bars = {symbol.upper(): bars_for_timeframe(symbol, request.timeframe)[0] for symbol in dict.fromkeys(request.symbols)}
        return DecisionDiagnostics().run(bars, request.timeframe, request.start_date, request.end_date, request.sampling_mode)
    except FileNotFoundError as error: raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error: raise HTTPException(422, str(error))


@router.get("/diagnostics/readiness")
def calibration_readiness():
    eligible = [x["symbol"] for x in universe(provider) if x["research_eligibility"] == "ELIGIBLE"]
    if not eligible: return readiness(universe(provider))
    bars = {symbol: bars_for_timeframe(symbol)[0] for symbol in eligible}
    return readiness(universe(provider), DecisionDiagnostics().run(bars, "1d", None, None, "TRANSITION"))
