from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.data import bars_for_source, bars_for_timeframe
from app.services.strategy_lab import FORMULA_VERSION, StrategyLabConfig, StrategyLabService
from app.services.strategy_lab_runs import StrategyLabRunStore
from app.services.research_metadata import local_csv_provenance

router = APIRouter(tags=["strategy-lab"])
run_store = StrategyLabRunStore(Path(__file__).resolve().parents[3] / "data" / "strategy_lab_runs")


class StrategyLabRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    cost_bps_per_side: float = Field(default=10.0, ge=0, le=500)
    confirmation_bars: int = Field(default=5, ge=0, le=10)
    max_hold_bars: int = Field(default=60, ge=5, le=120)
    snapshot_id: str | None = None
    snapshot_ids: dict[str, str] | None = None


def _prepare(request: StrategyLabRequest):
    symbols = list(dict.fromkeys(item.upper() for item in request.symbols))
    if request.timeframe != "1d":
        raise ValueError("策略实验室第一版仅支持日线，以确保下一日开盘执行语义一致")
    snapshot_ids = {symbol.upper(): snapshot_id for symbol, snapshot_id in (request.snapshot_ids or {}).items()}
    if snapshot_ids:
        if set(snapshot_ids) != set(symbols):
            raise ValueError("multi-snapshot research requires exactly one snapshot_id for every selected symbol")
        payload, manifests = {}, {}
        for symbol in symbols:
            bars, manifest = bars_for_source(symbol, request.timeframe, snapshot_ids[symbol])
            payload[symbol], manifests[symbol] = bars, {"snapshot_id": snapshot_ids[symbol], "code": manifest["code"], "data_sha256": manifest.get("data_sha256")}
        provenance = {"source": "futu_opend_snapshots", "timeframe": request.timeframe, "snapshots": manifests}
    elif request.snapshot_id:
        if len(symbols) != 1:
            raise ValueError("一个 OpenD 快照实验仅支持一个匹配标的")
        bars, snapshot = bars_for_source(symbols[0], request.timeframe, request.snapshot_id)
        payload = {symbols[0]: bars}
        manifests = {symbols[0]: {"snapshot_id": request.snapshot_id, "code": snapshot["code"], "data_sha256": snapshot.get("data_sha256")}}
        provenance = {"source": "futu_opend_snapshot", "snapshot_id": request.snapshot_id, "code": snapshot["code"], "timeframe": snapshot["timeframe"], "autype": snapshot.get("autype"), "data_sha256": snapshot.get("data_sha256")}
    else:
        payload = {symbol: bars_for_timeframe(symbol, request.timeframe)[0] for symbol in symbols}
        provenance = local_csv_provenance(payload, request.timeframe)
        manifests = provenance["datasets"]
    for symbol, bars in payload.items():
        if request.start_date:
            bars = bars[bars.date >= request.start_date]
        if request.end_date:
            bars = bars[bars.date <= request.end_date]
        payload[symbol] = bars
    if provenance["source"] == "local_csv":
        provenance = local_csv_provenance(payload, request.timeframe)
        manifests = provenance["datasets"]
    return payload, provenance, manifests


@router.post("/backtest/strategy-lab")
def strategy_lab(request: StrategyLabRequest):
    try:
        payload, provenance, _ = _prepare(request)
        config = StrategyLabConfig(cost_bps_per_side=request.cost_bps_per_side, confirmation_bars=request.confirmation_bars, max_hold_bars=request.max_hold_bars)
        return StrategyLabService(config).run(payload, data_provenance=provenance)
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.post("/backtest/strategy-lab/runs")
def create_strategy_lab_run(request: StrategyLabRequest):
    try:
        payload, provenance, manifests = _prepare(request)
        if len(payload) < 2:
            raise ValueError("全历史研究运行至少需要两个已锁定快照标的")
        frozen_request = request.model_dump()
        def runner(progress):
            config = StrategyLabConfig(cost_bps_per_side=request.cost_bps_per_side, confirmation_bars=request.confirmation_bars, max_hold_bars=request.max_hold_bars)
            cache_range = f"{request.start_date or 'FULL'}:{request.end_date or 'FULL'}"
            keys = {symbol.upper(): f"{manifest.get('snapshot_id')}:{manifest.get('data_sha256')}:{FORMULA_VERSION}:{cache_range}" for symbol, manifest in manifests.items()}
            return StrategyLabService(config).run(payload, data_provenance=provenance, forecast_cache=run_store.cache, forecast_keys=keys, progress=progress)
        return run_store.create_or_reuse(frozen_request, manifests, runner, research_context={"formula": FORMULA_VERSION})
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))
    except RuntimeError as error:
        raise HTTPException(409, str(error))


@router.get("/backtest/strategy-lab/runs/{run_id}")
def strategy_lab_run_status(run_id: str):
    try:
        return run_store.status(run_id)
    except FileNotFoundError:
        raise HTTPException(404, "STRATEGY_LAB_RUN_NOT_FOUND")


@router.get("/backtest/strategy-lab/runs/{run_id}/result")
def strategy_lab_run_result(run_id: str):
    try:
        return run_store.result(run_id)
    except FileNotFoundError:
        raise HTTPException(404, "STRATEGY_LAB_RUN_NOT_FOUND")
    except RuntimeError as error:
        raise HTTPException(409, str(error))


@router.get("/backtest/strategy-lab/runs/{run_id}/export")
def strategy_lab_run_export(run_id: str):
    try:
        return PlainTextResponse(run_store.export_csv(run_id), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="strategy-lab-{run_id}.csv"'})
    except FileNotFoundError:
        raise HTTPException(404, "STRATEGY_LAB_RUN_NOT_FOUND")
    except RuntimeError as error:
        raise HTTPException(409, str(error))
