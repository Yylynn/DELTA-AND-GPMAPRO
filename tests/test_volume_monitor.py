from datetime import date
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.data_freshness import freshness_snapshot
from app.services.volume_monitor import VolumeMonitor


def bars(volumes):
    count = len(volumes); dates = pd.date_range("2026-01-01", periods=count, freq="D")
    return pd.DataFrame({"date": dates, "open": [100] * count, "high": [102] * count, "low": [99] * count, "close": [100 + i for i in range(count)], "volume": volumes})


def test_volume_levels_and_anomalies():
    monitor = VolumeMonitor()
    assert monitor.snapshot(bars([100] * 20), "x", "1d")["volume_level"] == "NORMAL"
    high = monitor.snapshot(bars([100] * 19 + [150]), "x", "1d")
    assert high["volume_level"] == "HIGH" and high["volume_anomaly"] == "NONE"
    very_high = monitor.snapshot(bars([100] * 19 + [250]), "x", "1d")
    assert very_high["volume_level"] == "VERY_HIGH" and very_high["volume_anomaly"] == "SPIKE"
    dry = monitor.snapshot(bars([100] * 19 + [40]), "x", "1d")
    assert dry["volume_anomaly"] == "DRY_UP"


def test_expanding_contracting_and_short_history():
    monitor = VolumeMonitor()
    assert monitor.snapshot(bars([100] * 15 + [200] * 5), "x", "1d")["volume_trend"] == "EXPANDING"
    assert monitor.snapshot(bars([200] * 15 + [100] * 5), "x", "1d")["volume_trend"] == "CONTRACTING"
    assert monitor.snapshot(bars([100, 120, 130]), "x", "1d")["volume_ma20"] > 0


def test_as_of_fully_prevents_future_volume_leakage():
    monitor = VolumeMonitor(); source = bars([100] * 40); cutoff = "2026-01-20"
    expected = monitor.snapshot(source, "x", "1d", cutoff)
    mutated = source.copy(); mutated.loc[20:, "volume"] = 100000
    assert monitor.snapshot(mutated, "x", "1d", cutoff) == expected


def test_freshness_states_and_weekend_are_calendar_conservative():
    assert freshness_snapshot("2026-08-07", 10, date(2026, 8, 10))["freshness"] == "CURRENT"  # Friday to Monday
    assert freshness_snapshot("2026-08-04", 10, date(2026, 8, 10))["freshness"] == "STALE"
    assert freshness_snapshot("2026-07-31", 10, date(2026, 8, 10))["freshness"] == "VERY_STALE"
    assert freshness_snapshot(None, 0)["freshness"] == "UNKNOWN"


def test_all_zero_volume_is_rejected_in_snapshot_and_series_remains_json_safe(monkeypatch):
    source = bars([0, 0, 0])
    monitor = VolumeMonitor()
    with pytest.raises(ValueError, match="positive volume baseline"):
        monitor.snapshot(source, "ZERO", "1d")
    assert [row["relative_volume"] for row in monitor.series(source)] == [None, None, None]

    from app.api import volume as volume_api
    monkeypatch.setattr(volume_api, "bars_for_source", lambda *_: (source, {"source": "test"}))
    client = TestClient(app)
    assert client.get("/api/volume/ZERO").status_code == 422
    series = client.get("/api/volume/ZERO/series")
    assert series.status_code == 200
    assert all(row["relative_volume"] is None for row in series.json()["series"])


def test_zero_short_average_is_json_safe_when_long_average_exists(monkeypatch):
    source = bars([100] * 15 + [0] * 5)
    from app.api import volume as volume_api
    monkeypatch.setattr(volume_api, "bars_for_source", lambda *_: (source, {"source": "test"}))
    response = TestClient(app).get("/api/volume/ZERO5")
    assert response.status_code == 200
    assert response.json()["volume_ratio_5"] is None
    assert response.json()["relative_volume"] == 0
