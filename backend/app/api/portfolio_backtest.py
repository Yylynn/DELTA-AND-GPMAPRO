import csv
import io
import json
import pandas as pd

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.data import bars_for_source, bars_for_timeframe
from app.services.portfolio_backtest import PortfolioBacktestService
from app.services.research_metadata import local_csv_provenance, provenance_sha256, research_run_metadata

router = APIRouter(tags=["portfolio-backtest"])

class PortfolioBacktestRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    horizon: int = Field(default=10, gt=0, le=60)
    cost_bps_per_side: float = Field(default=10.0, ge=0, le=500)
    initial_capital: float = Field(default=100_000.0, gt=0)
    snapshot_id: str | None = None


def _bars_and_provenance(request: PortfolioBacktestRequest):
    symbols = list(dict.fromkeys(symbol.upper() for symbol in request.symbols))
    if request.snapshot_id:
        if len(symbols) != 1:
            raise ValueError("a Futu snapshot backtest accepts exactly one matching symbol")
        bars, snapshot = bars_for_source(symbols[0], request.timeframe, request.snapshot_id)
        return {symbols[0]: bars}, {"source": "futu_opend_snapshot", "snapshot_id": request.snapshot_id, "code": snapshot["code"], "timeframe": snapshot["timeframe"], "autype": snapshot.get("autype"), "data_sha256": snapshot.get("data_sha256")}
    frames = {symbol: bars_for_timeframe(symbol, request.timeframe)[0] for symbol in symbols}
    return frames, local_csv_provenance(frames, request.timeframe)

@router.post("/backtest/portfolio")
def portfolio_backtest(request: PortfolioBacktestRequest):
    try:
        bars, provenance = _bars_and_provenance(request)
        result = PortfolioBacktestService().run(bars, horizon=request.horizon, cost_bps=request.cost_bps_per_side, initial_capital=request.initial_capital, start_date=request.start_date, end_date=request.end_date)
        result["data_provenance"] = provenance
        result["run_metadata"] = research_run_metadata(
            parameters=request.model_dump(exclude={"snapshot_id"}),
            data_provenance=provenance,
            stable_context={"strategy": result["strategy"]},
        )
        return result
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/portfolio/export.csv")
def portfolio_backtest_export(request: PortfolioBacktestRequest):
    result = portfolio_backtest(request)
    output = io.StringIO(); writer = csv.writer(output)
    provenance = result.get("data_provenance", {})
    metadata = result["run_metadata"]
    provenance_json = json.dumps(provenance, ensure_ascii=False, sort_keys=True)
    writer.writerow(["kind", "date", "symbol", "entry_date", "exit_date", "entry_price", "exit_price", "gross_return", "net_return", "equity", "cash", "open_positions", "run_fingerprint", "git_commit", "snapshot_id", "data_sha256", "data_provenance"])
    for row in result["equity_curve"]: writer.writerow(["equity", row["date"], "", "", "", "", "", "", "", row["equity"], row["cash"], row["open_positions"], metadata["fingerprint"], metadata["git_commit"], provenance.get("snapshot_id", ""), provenance_sha256(provenance) or "", provenance_json])
    for trade in result["closed_trades"]: writer.writerow(["trade", "", trade["symbol"], trade["entry_date"], pd.Timestamp(trade["exit_date"]).date().isoformat(), trade["entry_price"], trade["exit_price"], trade["gross_return"], trade["net_return"], "", "", "", metadata["fingerprint"], metadata["git_commit"], provenance.get("snapshot_id", ""), provenance_sha256(provenance, trade["symbol"]) or "", provenance_json])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=portfolio-backtest.csv"})
