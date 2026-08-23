from fastapi import APIRouter, HTTPException

from app.api.data import bars_for_source
from app.services.signal_interpretation import SignalInterpretationService

router = APIRouter(tags=["signal interpretation"])
service = SignalInterpretationService()


@router.get("/interpretation/{symbol}")
def interpretation(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None, as_of: str | None = None):
    try:
        bars, source = bars_for_source(symbol, timeframe, snapshot_id)
        return service.interpret(bars, symbol, timeframe, source, as_of)
    except FileNotFoundError:
        raise HTTPException(404, "DATASET_NOT_FOUND")
    except ValueError as error:
        raise HTTPException(422, str(error))
