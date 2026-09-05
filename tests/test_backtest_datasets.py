import hashlib
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.data.providers import CsvDataProvider, validate_ohlcv
from app.main import app
from app.services.backtest_datasets import BacktestDatasetCatalog
from app.services.futu_snapshot import FutuSnapshotService
from app.services.market_snapshot import MarketDataError, MarketSnapshotService, YahooSnapshotService


def bars(count: int = 300) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=count)
    close = pd.Series(range(count), dtype=float) / 10 + 100
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close + .25,
        "volume": 1_000,
    })


def build_catalog(tmp_path) -> BacktestDatasetCatalog:
    provider = CsvDataProvider(tmp_path / "imported")
    local = bars()
    provider.save("US.LOCAL", local.to_csv(index=False).encode())

    snapshots = FutuSnapshotService(tmp_path / "snapshots")
    snapshot, _ = validate_ohlcv(bars(760))
    snapshot_id = "US_FUTU_1D_QFQ_20260820T000000Z"
    payload = snapshot.to_csv(index=False, lineterminator="\n").encode()
    manifest = {
        "snapshot_id": snapshot_id,
        "source": "futu_opend",
        "code": "US.FUTU",
        "timeframe": "1d",
        "autype": "QFQ",
        "fetched_at": "20260820T000000Z",
        "start_date": str(snapshot.date.iloc[0]),
        "end_date": str(snapshot.date.iloc[-1]),
        "bar_count": len(snapshot),
        "data_sha256": hashlib.sha256(payload).hexdigest(),
        "quality": "通过",
        "warnings": [],
    }
    (snapshots.root / f"{snapshot_id}.csv").write_bytes(payload)
    (snapshots.root / f"{snapshot_id}.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return BacktestDatasetCatalog(provider, snapshots)


def test_catalog_unifies_local_csv_and_futu_snapshots(tmp_path):
    catalog = build_catalog(tmp_path)

    rows = catalog.list()

    assert {(row["source"], row["symbol"]) for row in rows} == {
        ("local_csv", "US.LOCAL"),
        ("futu_snapshot", "US.FUTU"),
    }
    local = next(row for row in rows if row["source"] == "local_csv")
    futu = next(row for row in rows if row["source"] == "futu_snapshot")
    assert local["adjustment"] == "UNRECORDED"
    assert local["research_eligibility"] == "LIMITED"
    assert futu["adjustment"] == "QFQ"
    assert futu["research_eligibility"] == "ELIGIBLE"


def test_load_revalidates_and_fingerprints_the_selection(tmp_path):
    catalog = build_catalog(tmp_path)
    local_id = next(
        row["dataset_id"] for row in catalog.list() if row["source"] == "local_csv"
    )

    result = catalog.load([local_id, local_id])

    assert result["dataset_count"] == 1
    assert result["source"] == "local_csv"
    assert result["datasets"][0]["verification"] == "VERIFIED"
    assert len(result["selection_id"]) == 64
    assert result["common_date_range"] == {
        "start": result["datasets"][0]["start_date"],
        "end": result["datasets"][0]["end_date"],
    }


def test_backtest_dataset_api_uses_the_unified_contract(monkeypatch, tmp_path):
    from app.api import backtest_datasets as dataset_api

    catalog = build_catalog(tmp_path)
    monkeypatch.setattr(dataset_api, "catalog", catalog)
    client = TestClient(app)

    response = client.get("/api/backtest/datasets")
    assert response.status_code == 200
    assert response.json()["counts"] == {"local_csv": 1, "futu_snapshot": 1}

    dataset_id = next(
        row["dataset_id"]
        for row in response.json()["datasets"]
        if row["source"] == "futu_snapshot"
    )
    loaded = client.post(
        "/api/backtest/datasets/load", json={"dataset_ids": [dataset_id]}
    )
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["datasets"][0]["verification"] == "VERIFIED"


class StubTicker:
    def __init__(self, calls: list[dict], error: Exception | None = None):
        self.calls = calls
        self.error = error

    def history(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        frame = bars(760).rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        })
        frame["Date"] = pd.to_datetime(frame.pop("date"))
        return frame.set_index("Date")


def build_symbol_catalog(tmp_path, *, error: Exception | None = None):
    provider = CsvDataProvider(tmp_path / "imported")
    futu = FutuSnapshotService(tmp_path / "futu")
    calls: list[dict] = []
    ticker = StubTicker(calls, error)
    yahoo = YahooSnapshotService(tmp_path / "market", ticker_factory=lambda _: ticker)
    market = MarketSnapshotService("yahoo", yahoo=yahoo, futu=futu)
    return BacktestDatasetCatalog(provider, futu, market), yahoo, calls


@pytest.mark.parametrize(
    ("code", "normalised"),
    [
        ("AAPL", "US.AAPL"),
        ("HK.00700", "HK.00700"),
        ("SH.600519", "SH.600519"),
        ("SZ.000001", "SZ.000001"),
    ],
)
def test_symbol_load_supports_us_hk_and_a_share_codes(tmp_path, code, normalised):
    catalog, _, calls = build_symbol_catalog(tmp_path)

    result = catalog.load_symbol(code)

    assert result["provider"] == "yahoo"
    assert result["cache_status"] == "FETCHED"
    assert result["dataset_count"] == 1
    assert result["datasets"][0]["symbol"] == normalised
    assert result["datasets"][0]["dataset_id"].startswith("market_snapshot:YAHOO_")
    assert result["datasets"][0]["verification"] == "VERIFIED"
    assert calls[0]["start"] == "2018-01-01"
    assert calls[0]["interval"] == "1d"
    assert calls[0]["auto_adjust"] is True


def test_symbol_load_reuses_today_and_refreshes_on_request(tmp_path):
    catalog, _, calls = build_symbol_catalog(tmp_path)

    first = catalog.load_symbol("US.AAPL")
    cached = catalog.load_symbol("AAPL")
    refreshed = catalog.load_symbol("US.AAPL", refresh=True)

    assert first["cache_status"] == "FETCHED"
    assert cached["cache_status"] == "HIT"
    assert cached["datasets"][0]["snapshot_id"] == first["datasets"][0]["snapshot_id"]
    assert refreshed["cache_status"] == "REFRESHED"
    assert refreshed["datasets"][0]["snapshot_id"] != first["datasets"][0]["snapshot_id"]
    assert len(calls) == 2


def test_symbol_load_fetches_again_when_cache_is_from_an_earlier_day(tmp_path):
    catalog, yahoo, calls = build_symbol_catalog(tmp_path)
    first = catalog.load_symbol("US.AAPL")
    snapshot_id = first["datasets"][0]["snapshot_id"]
    manifest_path = yahoo.root / f"{snapshot_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fetched_at"] = "20200101T000000000000Z"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = catalog.load_symbol("US.AAPL")

    assert result["cache_status"] == "FETCHED"
    assert result["datasets"][0]["snapshot_id"] != snapshot_id
    assert len(calls) == 2


def test_symbol_load_revalidates_cached_snapshot_integrity(tmp_path):
    catalog, yahoo, _ = build_symbol_catalog(tmp_path)
    first = catalog.load_symbol("US.AAPL")
    snapshot_id = first["datasets"][0]["snapshot_id"]
    csv_path = yahoo.root / f"{snapshot_id}.csv"
    frame = pd.read_csv(csv_path)
    frame.loc[0, "close"] += 10
    frame.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="SNAPSHOT_INTEGRITY_ERROR"):
        catalog.load_symbol("US.AAPL")


def test_symbol_load_api_contract_and_error_mapping(monkeypatch):
    from app.api import backtest_datasets as dataset_api

    class Catalog:
        def __init__(self):
            self.requests = []

        def load_symbol(self, code, *, refresh=False):
            self.requests.append((code, refresh))
            return {
                "selection_id": "a" * 64,
                "datasets": [{"dataset_id": "market_snapshot:test", "symbol": code}],
                "provider": "yahoo",
                "cache_status": "REFRESHED" if refresh else "HIT",
                "snapshot_fetched_at": "20260903T000000000000Z",
            }

    catalog = Catalog()
    monkeypatch.setattr(dataset_api, "catalog", catalog)
    client = TestClient(app)
    response = client.post("/api/backtest/symbol/load", json={"code": "US.AAPL", "refresh": True})
    assert response.status_code == 200
    assert response.json()["cache_status"] == "REFRESHED"
    assert catalog.requests == [("US.AAPL", True)]

    catalog.load_symbol = lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad code"))
    assert client.post("/api/backtest/symbol/load", json={"code": "bad"}).status_code == 422

    catalog.load_symbol = lambda *_args, **_kwargs: (_ for _ in ()).throw(MarketDataError("offline"))
    assert client.post("/api/backtest/symbol/load", json={"code": "US.AAPL"}).status_code == 503
