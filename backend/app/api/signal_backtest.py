import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.data import bars_for_source, bars_for_timeframe
from app.services.signal_backtest import SignalBacktestService

router = APIRouter(tags=["signal-backtest"])

class SignalBacktestRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    horizons: list[int] = Field(default=[5, 10, 20], min_length=1)
    cost_bps_per_side: float = Field(default=10.0, ge=0, le=500)
    snapshot_id: str | None = None


def _bars_and_provenance(request: SignalBacktestRequest):
    symbols = list(dict.fromkeys(symbol.upper() for symbol in request.symbols))
    if request.snapshot_id:
        if len(symbols) != 1:
            raise ValueError("a Futu snapshot backtest accepts exactly one matching symbol")
        bars, snapshot = bars_for_source(symbols[0], request.timeframe, request.snapshot_id)
        return {symbols[0]: bars}, {"source": "futu_opend_snapshot", "snapshot_id": request.snapshot_id, "code": snapshot["code"], "timeframe": snapshot["timeframe"], "autype": snapshot.get("autype"), "data_sha256": snapshot.get("data_sha256")}
    return ({symbol: bars_for_timeframe(symbol, request.timeframe)[0] for symbol in symbols}, {"source": "local_csv", "timeframe": request.timeframe})

@router.post("/backtest/signals")
def signal_backtest(request: SignalBacktestRequest):
    try:
        if any(horizon <= 0 for horizon in request.horizons):
            raise ValueError("horizons must be positive")
        bars, provenance = _bars_and_provenance(request)
        return SignalBacktestService().run(bars, horizons=tuple(request.horizons), cost_bps=request.cost_bps_per_side, start_date=request.start_date, end_date=request.end_date, data_provenance=provenance)
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/signals/export.csv")
def signal_backtest_export(request: SignalBacktestRequest):
    result = signal_backtest(request)
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["kind", "symbol", "signal", "horizon", "date", "exit_date", "side", "gross_return", "net_return", "mfe", "mae", "sample_count", "aggregation", "run_fingerprint", "snapshot_id", "data_sha256"])
    fingerprint = result["run_metadata"]["fingerprint"]
    provenance = result["run_metadata"].get("data_provenance", {})
    for symbol, values in result["symbols"].items():
        for trade in values["trades"]:
            writer.writerow(["trade", symbol, trade["signal"], trade["horizon"], trade["date"], trade["exit_date"], trade["side"], trade["gross_return"], trade["net_return"], trade["mfe"], trade["mae"], "", "", fingerprint, provenance.get("snapshot_id", ""), provenance.get("data_sha256", "")])
    for signal, horizons in result["pooled"]["groups"].items():
        for horizon, stats in horizons.items():
            writer.writerow(["summary", "ALL", signal, horizon, "", "", "", "", stats["average_net_return"], stats["average_mfe"], stats["average_mae"], stats["sample_count"], stats.get("aggregation", ""), fingerprint, provenance.get("snapshot_id", ""), provenance.get("data_sha256", "")])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=signal-backtest.csv"})
