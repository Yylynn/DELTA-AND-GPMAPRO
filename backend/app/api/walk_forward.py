from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.data import bars_for_source, bars_for_timeframe
from app.services.walk_forward import WalkForwardService
from app.services.research_metadata import local_csv_provenance, research_run_metadata

router = APIRouter(tags=["walk-forward"])

class WalkForwardRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    horizon: int = Field(default=10, gt=0, le=60)
    cost_bps_per_side: float = Field(default=10.0, ge=0, le=500)
    test_bars: int = Field(default=63, gt=0)
    step_bars: int = Field(default=63, gt=0)
    min_history_bars: int = Field(default=252, gt=0)
    snapshot_id: str | None = None

@router.post("/backtest/walk-forward")
def walk_forward(request: WalkForwardRequest):
    try:
        symbols = list(dict.fromkeys(symbol.upper() for symbol in request.symbols))
        if request.snapshot_id:
            if len(symbols) != 1:
                raise ValueError("a Futu snapshot walk-forward run accepts exactly one matching symbol")
            bars, snapshot = bars_for_source(symbols[0], request.timeframe, request.snapshot_id)
            payload, provenance = {symbols[0]: bars}, {"source": "futu_opend_snapshot", "snapshot_id": request.snapshot_id, "code": snapshot["code"], "timeframe": snapshot["timeframe"], "autype": snapshot.get("autype"), "data_sha256": snapshot.get("data_sha256")}
        else:
            payload = {symbol: bars_for_timeframe(symbol, request.timeframe)[0] for symbol in symbols}
            provenance = local_csv_provenance(payload, request.timeframe)
        result = WalkForwardService().run(payload, horizon=request.horizon, cost_bps=request.cost_bps_per_side, test_bars=request.test_bars, step_bars=request.step_bars, min_history_bars=request.min_history_bars)
        result["data_provenance"] = provenance
        result["run_metadata"] = research_run_metadata(
            parameters=request.model_dump(exclude={"snapshot_id"}),
            data_provenance=provenance,
            stable_context={"strategy": result["strategy"], "validation": "walk_forward"},
        )
        return result
    except FileNotFoundError as error: raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error: raise HTTPException(422, str(error))
