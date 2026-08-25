import hashlib
import json

import pandas as pd
from fastapi.testclient import TestClient

from app.data.providers import CsvDataProvider, validate_ohlcv
from app.main import app
from app.services.backtest_datasets import BacktestDatasetCatalog
from app.services.futu_snapshot import FutuSnapshotService


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
