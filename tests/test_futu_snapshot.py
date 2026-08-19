import json

import pandas as pd

from app.api.itd import project_display_dates
from app.services.futu_snapshot import FutuSnapshotService


def test_snapshot_load_is_separate_from_imported_csv_and_lists_newest_first(tmp_path):
    service = FutuSnapshotService(tmp_path)
    frame = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "open": [1, 2], "high": [2, 3], "low": [1, 2], "close": [2, 3], "volume": [100, 200]})
    first = {"snapshot_id": "US_AAPL_1D_QFQ_20240101T000000Z", "code": "US.AAPL", "timeframe": "1d", "autype": "QFQ", "fetched_at": "20240101T000000Z"}
    second = {**first, "snapshot_id": "US_AAPL_1D_QFQ_20240102T000000Z", "fetched_at": "20240102T000000Z"}
    for manifest in (first, second):
        frame.to_csv(tmp_path / f"{manifest['snapshot_id']}.csv", index=False)
        (tmp_path / f"{manifest['snapshot_id']}.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert [item["snapshot_id"] for item in service.list()] == [second["snapshot_id"], first["snapshot_id"]]
    loaded, metadata = service.load(first["snapshot_id"])
    assert len(loaded) == 2 and metadata["source"] == "futu_opend_snapshot"
    assert len(metadata["data_sha256"]) == 64


def test_snapshot_codes_are_market_qualified_and_not_aapl_specific(tmp_path):
    service = FutuSnapshotService(tmp_path)
    assert service._normalise_code("us.msft") == "US.MSFT"
    assert service._normalise_code("HK.00700") == "HK.00700"
    assert service._normalise_code("sh.600519") == "SH.600519"
    assert service._normalise_code("sz.000001") == "SZ.000001"
    try:
        service._normalise_code("AAPL")
    except ValueError:
        pass
    else:
        raise AssertionError("a market-qualified Futu code is required")


def test_unreachable_opend_fails_before_sdk_retry_loop(tmp_path):
    service = FutuSnapshotService(tmp_path, host="127.0.0.1", port=1)
    try:
        service._ensure_endpoint()
    except Exception as error:
        assert "OpenD is unavailable" in str(error)
    else:
        raise AssertionError("unreachable OpenD endpoint must fail fast")


def test_snapshot_ohlcv_resamples_through_the_same_source_path(monkeypatch, tmp_path):
    from app.api import data as data_api
    service = FutuSnapshotService(tmp_path)
    frame = pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"],
        "open": [10, 11, 12, 13], "high": [11, 12, 13, 14],
        "low": [9, 10, 11, 12], "close": [10.5, 11.5, 12.5, 13.5], "volume": [100, 200, 300, 400],
    })
    manifest = {"snapshot_id": "US_TEST_1D_QFQ_20240101T000000Z", "code": "US.TEST", "timeframe": "1d", "autype": "QFQ", "fetched_at": "20240101T000000Z"}
    frame.to_csv(tmp_path / f"{manifest['snapshot_id']}.csv", index=False)
    (tmp_path / f"{manifest['snapshot_id']}.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(data_api, "futu_snapshots", service)
    result = data_api.futu_snapshot_ohlcv(manifest["snapshot_id"], timeframe="1w")
    assert len(result["bars"]) == 2
    assert result["snapshot"]["timeframe"] == "1w"
    assert result["snapshot"]["resampled_from"] == "1d"


def test_snapshot_monthly_resample_uses_month_ohlcv_and_last_real_trading_date(monkeypatch, tmp_path):
    from app.api import data as data_api
    service = FutuSnapshotService(tmp_path)
    frame = pd.DataFrame({
        "date": ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"],
        "open": [10, 11, 20, 21], "high": [12, 13, 24, 25],
        "low": [9, 8, 19, 18], "close": [11, 12, 23, 22], "volume": [100, 200, 300, 400],
    })
    manifest = {"snapshot_id": "US_TEST_1D_QFQ_20240102T000000Z", "code": "US.TEST", "timeframe": "1d", "autype": "QFQ", "fetched_at": "20240102T000000Z"}
    frame.to_csv(tmp_path / f"{manifest['snapshot_id']}.csv", index=False)
    (tmp_path / f"{manifest['snapshot_id']}.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(data_api, "futu_snapshots", service)
    result = data_api.futu_snapshot_ohlcv(manifest["snapshot_id"], timeframe="1mo")
    assert [(row["date"], row["open"], row["high"], row["low"], row["close"], row["volume"]) for row in result["bars"]] == [
        ("2024-01-31", 10, 13, 8, 12, 300), ("2024-02-02", 20, 25, 18, 22, 700),
    ]
    assert result["snapshot"]["timeframe"] == "1mo"
    assert result["snapshot"]["resampled_from"] == "1d"


def test_itd_daily_dates_project_to_the_final_actual_weekly_or_monthly_bar():
    # 2024-01-15 is a US market holiday, so the weekly bar ends on Thursday.
    daily = pd.DataFrame({"date": ["2024-01-11", "2024-01-12", "2024-01-16", "2024-01-31", "2024-02-01", "2024-02-02"]})
    weekly = pd.DataFrame({"date": ["2024-01-12", "2024-01-16", "2024-01-31", "2024-02-02"]})
    monthly = pd.DataFrame({"date": ["2024-01-31", "2024-02-02"]})

    weekly_projection = project_display_dates(daily, weekly, "1w")
    monthly_projection = project_display_dates(daily, monthly, "1mo")

    assert weekly_projection["2024-01-11"] == "2024-01-12"
    assert weekly_projection["2024-01-16"] == "2024-01-16"
    assert monthly_projection["2024-01-11"] == "2024-01-31"
    assert monthly_projection["2024-02-01"] == "2024-02-02"
