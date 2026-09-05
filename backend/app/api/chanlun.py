"""Read-only simplified Chanlun view over one immutable research snapshot."""

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.api.data import bars_for_source
from app.quant.chanlun import chanlun_analyze

router = APIRouter(tags=["Chanlun"])


@router.get("/chanlun/{symbol}")
def chanlun(symbol: str, timeframe: str = "1d", snapshot_id: str | None = None):
    if timeframe != "1d":
        raise HTTPException(422, "缠论图层目前仅支持 1d 日线快照")
    try:
        bars, source = bars_for_source(symbol, "1d", snapshot_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "未找到该代码的日线研究快照")
    result = chanlun_analyze(bars)
    return {"symbol": str(source.get("code") or symbol).upper(), "timeframe": "1d", "source": source, **result}
