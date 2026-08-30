"""HTTP contract for the fixed US_ETF_SHORT_V1 signal-rule protocol."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.data import bars_for_source, bars_for_timeframe
from app.services.research_metadata import local_csv_provenance
from app.services.signal_rule_research import DEFAULT_SYMBOLS, PROTOCOL_ID, SignalRuleResearchService

router = APIRouter(tags=["signal-rule-research"])


class SignalRulesRequest(BaseModel):
    protocol_id: str = PROTOCOL_ID
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS), min_length=1)
    timeframe: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    # The protocol has fixed 5/10/20bp scenarios.  The field documents the
    # caller's requested scenarios and rejects unregistered parameter fishing.
    cost_scenarios_bps_per_side: list[float] = Field(default_factory=lambda: [5, 10, 20])
    snapshot_id: str | None = None
    snapshot_ids: dict[str, str] | None = None


def _prepare(request: SignalRulesRequest) -> tuple[dict, dict]:
    if request.protocol_id != PROTOCOL_ID:
        raise ValueError(f"only the pre-registered protocol {PROTOCOL_ID} is available")
    if request.timeframe != "1d":
        raise ValueError("US_ETF_SHORT_V1 only supports daily bars")
    if sorted(set(float(x) for x in request.cost_scenarios_bps_per_side)) != [5.0, 10.0, 20.0]:
        raise ValueError("US_ETF_SHORT_V1 fixes cost scenarios at 5, 10, and 20 bp per side")
    symbols = list(dict.fromkeys(x.upper() for x in request.symbols))
    snapshot_ids = {k.upper(): v for k, v in (request.snapshot_ids or {}).items()}
    if snapshot_ids and set(snapshot_ids) != set(symbols):
        raise ValueError("snapshot_ids must contain exactly one immutable snapshot for every selected symbol")
    if request.snapshot_id and (snapshot_ids or len(symbols) != 1):
        raise ValueError("snapshot_id is only valid for a single-symbol request; use snapshot_ids for a basket")
    bars, manifests = {}, {}
    for symbol in symbols:
        if snapshot_ids:
            frame, manifest = bars_for_source(symbol, "1d", snapshot_ids[symbol])
            manifests[symbol] = {"snapshot_id": snapshot_ids[symbol], "code": manifest.get("code"), "data_sha256": manifest.get("data_sha256")}
        elif request.snapshot_id:
            frame, manifest = bars_for_source(symbol, "1d", request.snapshot_id)
            manifests[symbol] = {"snapshot_id": request.snapshot_id, "code": manifest.get("code"), "data_sha256": manifest.get("data_sha256")}
        else:
            frame = bars_for_timeframe(symbol, "1d")[0]
        if request.start_date: frame = frame[frame.date >= request.start_date]
        if request.end_date: frame = frame[frame.date <= request.end_date]
        bars[symbol] = frame.reset_index(drop=True)
    provenance = ({"source": "futu_opend_snapshots", "timeframe": "1d", "snapshots": manifests} if manifests else local_csv_provenance(bars, "1d"))
    return bars, provenance


@router.post("/backtest/signal-rules")
def signal_rules(request: SignalRulesRequest):
    try:
        bars, provenance = _prepare(request)
        return SignalRuleResearchService().run(bars, data_provenance=provenance)
    except FileNotFoundError as error:
        raise HTTPException(404, f"DATASET_NOT_FOUND: {error}")
    except ValueError as error:
        raise HTTPException(422, str(error))
