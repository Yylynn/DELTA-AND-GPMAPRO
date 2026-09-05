import importlib

import pandas as pd
import pytest
from fastapi import HTTPException

from app.quant.chanlun import chanlun_analyze

chanlun_api = importlib.import_module("app.api.chanlun")


def bars() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=9, freq="B"),
        "open": [10, 11, 12, 9, 8, 11, 13, 10, 9],
        "high": [11, 13, 14, 10, 9, 13, 15, 11, 10],
        "low": [9, 10, 11, 7, 6, 10, 12, 8, 7],
        "close": [10, 12, 12, 8, 8, 12, 14, 9, 8],
        "volume": [100] * 9,
    })


def test_chanlun_reports_insufficient_and_invalid_ohlc_explicitly():
    assert chanlun_analyze(bars().head(2))["status"] == "INSUFFICIENT_DATA"
    invalid = bars().drop(columns=["high"])
    assert chanlun_analyze(invalid)["status"] == "INVALID_DATA"


def test_chanlun_structure_is_deterministic_for_same_snapshot_input():
    first = chanlun_analyze(bars())
    second = chanlun_analyze(bars())
    assert first["status"] == "AVAILABLE"
    assert first == second
    assert {"fractals", "bis", "zhongshus", "points", "latest_bi", "conclusion"}.issubset(first)


def test_chanlun_api_uses_requested_daily_snapshot_only(monkeypatch):
    source = bars()
    captured = []
    monkeypatch.setattr(chanlun_api, "bars_for_source", lambda symbol, timeframe, snapshot_id: (captured.append((symbol, timeframe, snapshot_id)) or source, {"code": "US.TEST", "snapshot_id": snapshot_id}))

    response = chanlun_api.chanlun("TEST", snapshot_id="snapshot-1")

    assert response["symbol"] == "US.TEST"
    assert response["timeframe"] == "1d"
    assert captured == [("TEST", "1d", "snapshot-1")]


def test_chanlun_api_rejects_non_daily_requests():
    with pytest.raises(HTTPException) as error:
        chanlun_api.chanlun("TEST", timeframe="1w")
    assert error.value.status_code == 422
