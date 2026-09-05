import json

import pandas as pd
import pytest

from app.services.futu_snapshot import FutuSnapshotService
from app.services.market_snapshot import MarketSnapshotService, YahooSnapshotService


class FakeTicker:
    def __init__(self):
        self.kwargs = None

    def history(self, **kwargs):
        self.kwargs = kwargs
        return pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0, 13.0],
                "High": [11.0, 12.0, 13.0, 14.0],
                "Low": [9.0, 10.0, 11.0, 12.0],
                "Close": [10.5, 11.5, 12.5, 13.5],
                "Volume": [100, 200, 300, 400],
            },
            index=pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"], name="Date"),
        )


class RepairFallbackTicker(FakeTicker):
    def __init__(self):
        super().__init__()
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["repair"]:
            error = ModuleNotFoundError("No module named 'sklearn'")
            error.name = "sklearn"
            raise error
        return super().history(**kwargs)


def test_yahoo_code_mapping_and_validation(tmp_path):
    service = YahooSnapshotService(tmp_path, ticker_factory=lambda _: FakeTicker())
    assert service.normalise_code("AAPL") == ("US.AAPL", "AAPL")
    assert service.normalise_code("HK.700") == ("HK.700", "0700.HK")
    assert service.normalise_code("HK.00700") == ("HK.00700", "0700.HK")
    assert service.normalise_code("SH.600519") == ("SH.600519", "600519.SS")
    assert service.normalise_code("SZ.000001") == ("SZ.000001", "000001.SZ")
    with pytest.raises(ValueError):
        service.normalise_code("JP.7203")


def test_yahoo_snapshot_includes_requested_end_and_is_immutable(tmp_path):
    ticker = FakeTicker()
    service = YahooSnapshotService(tmp_path, ticker_factory=lambda _: ticker)
    manifest = service.fetch_history_snapshot("US.AAPL", start="2024-01-01", end="2024-01-08")
    assert ticker.kwargs["end"] == "2024-01-09"
    assert ticker.kwargs["auto_adjust"] is True
    assert ticker.kwargs["repair"] is True
    assert manifest["provider"] == "yahoo"
    assert manifest["provider_symbol"] == "AAPL"
    assert manifest["autype"] == "QFQ"
    frame, loaded = service.load(manifest["snapshot_id"])
    assert len(frame) == 4
    assert loaded["source"] == "yahoo_snapshot"
    assert loaded["data_sha256"] == manifest["data_sha256"]

    csv_path = tmp_path / f"{manifest['snapshot_id']}.csv"
    changed = pd.read_csv(csv_path)
    changed.loc[0, "close"] = 999
    changed.to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="SNAPSHOT_INTEGRITY_ERROR"):
        service.load(manifest["snapshot_id"])


def test_weekly_snapshot_is_resampled_from_daily_bars(tmp_path):
    service = YahooSnapshotService(tmp_path, ticker_factory=lambda _: FakeTicker())
    manifest = service.fetch_history_snapshot("US.AAPL", timeframe="1w", start="2024-01-01", end="2024-01-08")
    frame, _ = service.load(manifest["snapshot_id"])
    assert frame.date.tolist() == ["2024-01-05", "2024-01-08"]
    assert frame.volume.tolist() == [600, 400]
    assert manifest["daily_source_bar_count"] == 4


def test_yahoo_snapshot_retries_without_repair_when_sklearn_is_missing(tmp_path):
    ticker = RepairFallbackTicker()
    service = YahooSnapshotService(tmp_path, ticker_factory=lambda _: ticker)

    manifest = service.fetch_history_snapshot("SH.600519", start="2024-01-01", end="2024-01-08")

    assert [call["repair"] for call in ticker.calls] == [True, False]
    assert manifest["history_repair"] == "disabled_missing_sklearn"


def test_market_facade_reads_legacy_futu_snapshot(tmp_path):
    yahoo_root, futu_root = tmp_path / "market", tmp_path / "futu"
    futu = FutuSnapshotService(futu_root)
    snapshot_id = "US_AAPL_1D_QFQ_20240101T000000Z"
    frame = pd.DataFrame({"date": ["2024-01-02"], "open": [10], "high": [11], "low": [9], "close": [10], "volume": [100]})
    frame.to_csv(futu_root / f"{snapshot_id}.csv", index=False)
    (futu_root / f"{snapshot_id}.json").write_text(json.dumps({"snapshot_id": snapshot_id, "code": "US.AAPL", "timeframe": "1d", "autype": "QFQ", "fetched_at": "20240101T000000Z"}), encoding="utf-8")
    facade = MarketSnapshotService("yahoo", YahooSnapshotService(yahoo_root, ticker_factory=lambda _: FakeTicker()), futu)
    loaded, metadata = facade.load(snapshot_id)
    assert len(loaded) == 1
    assert metadata["source"] == "futu_opend_snapshot"
