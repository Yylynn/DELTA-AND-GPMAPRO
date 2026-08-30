from datetime import UTC, datetime, timedelta

import pandas as pd

from app.services.option_monitor import OptionMonitorService


class Client:
    def __init__(self, volumes, scheduled=False):
        self.volumes, self.scheduled, self.index = volumes, scheduled, 0

    def fetch(self, code, now):
        volume = self.volumes[min(self.index, len(self.volumes) - 1)]
        self.index += 1
        expiry = (now.date() + timedelta(days=20)).isoformat()
        chain = pd.DataFrame([
            {"code": f"{code}C", "strike_price": 100, "strike_time": expiry, "option_type": "CALL"},
            {"code": f"{code}P", "strike_price": 100, "strike_time": expiry, "option_type": "PUT"},
        ])
        quotes = pd.DataFrame([
            {"code": f"{code}C", "underlying_price": 100, "underlying_volume": 100_000, "bid_price": 2, "ask_price": 2.1, "volume": volume, "open_interest": 100, "implied_volatility": .35, "delta": .5},
            {"code": f"{code}P", "underlying_price": 100, "underlying_volume": 100_000, "bid_price": 2, "ask_price": 2.1, "volume": 2, "open_interest": 100, "implied_volatility": .32, "delta": -.5},
        ])
        return chain, quotes, self.scheduled


def clock(values):
    iterator = iter(values)
    return lambda: next(iterator)


def test_monitor_warms_then_keeps_immutable_evidence_and_flags_spike(tmp_path):
    start = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    moments = [start + timedelta(days=index) for index in range(21)]
    volumes = [entry for value in list(range(10, 30)) + [500] for entry in [value, *([10] * 7)]]
    service = OptionMonitorService(tmp_path, client=Client(volumes), now=clock(moments))
    for _ in range(20):
        result = service.check(requested="AAPL")
        assert result["status"] == "OK"
    result = service.check(requested="AAPL")
    assert result["created_alerts"]
    alert = result["created_alerts"][0]
    assert alert["snapshot_id"].startswith("US_AAPL_")
    assert any(signal["kind"] == "ATTENTION_SURGE" for signal in alert["signals"])
    assert (tmp_path / f"{alert['snapshot_id']}.csv").exists()
    assert (tmp_path / f"{alert['snapshot_id']}.json").exists()
    insight = service.insight("US.AAPL")
    assert insight["status"] == "AVAILABLE"
    assert len(insight["contracts"]) == 2


def test_scheduled_event_downweights_directional_hypothesis(tmp_path):
    start = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    moments = [start + timedelta(days=index) for index in range(21)]
    volumes = [entry for value in list(range(10, 30)) + [500] for entry in [value, *([10] * 7)]]
    service = OptionMonitorService(tmp_path, client=Client(volumes, scheduled=True), now=clock(moments))
    for _ in range(20): service.check(requested="AAPL")
    alert = service.check(requested="AAPL")["created_alerts"][0]
    directional = next(signal for signal in alert["signals"] if signal["kind"] == "DIRECTIONAL_HYPOTHESIS")
    assert directional["scheduled_event"] is True
    assert directional["severity"] == "INFO"
    assert directional["confidence"] <= .2


def test_empty_chain_is_partial_and_does_not_create_alert(tmp_path):
    class Empty:
        def fetch(self, code, now): return pd.DataFrame(), pd.DataFrame(), False
    service = OptionMonitorService(tmp_path, client=Empty(), now=lambda: datetime(2026, 8, 3, 15, tzinfo=UTC))
    result = service.check(requested="AAPL")
    assert result["status"] == "PARTIAL"
    assert result["created_alerts"] == []
    assert result["failures"][0]["error"] == "EMPTY_CHAIN"
