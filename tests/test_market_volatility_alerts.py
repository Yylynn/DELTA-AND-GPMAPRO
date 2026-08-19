import time
from datetime import UTC, datetime

import pandas as pd

from app.services.market_volatility_alerts import MarketVolatilityAlertService


def frame(previous: float, current: float) -> pd.DataFrame:
    return pd.DataFrame({"date": ["2026-08-17", "2026-08-18"], "close": [previous, current]})


def test_daily_change_at_three_percent_creates_one_alert_and_deduplicates(tmp_path):
    values = {"^VIX": frame(20, 20.6), "^VXN": frame(20, 20), "^VVIX": frame(20, 20), "VIXY": frame(20, 20)}
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda code: values[code])
    first = service.check()
    assert [(item["label"], item["reason_kind"]) for item in first["created_alerts"]] == [("VIX", "DAILY_CHANGE"), ("VIX", "WATCH_LEVEL")]
    assert service.check()["created_alerts"] == []


def test_multiple_indicators_and_risk_level_are_reported(tmp_path):
    values = {"^VIX": frame(24, 25.2), "^VXN": frame(29, 30), "^VVIX": frame(10, 10.3), "VIXY": frame(10, 10.3)}
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda code: values[code])
    result = service.check()
    assert {item["label"] for item in result["created_alerts"]} == {"VIX", "VXN", "VVIX", "VIXY"}
    assert any(item["severity"] == "RISK" and item["label"] == "VIX" for item in result["created_alerts"])
    assert any(item["severity"] == "RISK" and item["label"] == "VXN" for item in result["created_alerts"])


def test_fetch_failure_is_reported_without_creating_alert(tmp_path):
    def fetch(code: str):
        if code == "^VIX": raise RuntimeError("Yahoo Finance unavailable")
        return frame(10, 10)
    service = MarketVolatilityAlertService(tmp_path, fetcher=fetch)
    result = service.check()
    assert result["last_check"]["status"] == "PARTIAL"
    assert result["failures"] == [{"id": "vix", "label": "VIX", "code": "^VIX", "error": "Yahoo Finance unavailable"}]
    assert result["created_alerts"] == []


def test_config_requires_all_four_indicators(tmp_path):
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda _: frame(10, 10))
    try:
        service.update_config({"change_threshold_pct": 3, "indicators": []})
    except ValueError as error:
        assert "vix" in str(error)
    else:
        raise AssertionError("all four indicators must be required")


def test_stalled_public_request_returns_failure_without_blocking_ui(tmp_path):
    def slow_fetch(_: str):
        time.sleep(.05)
        return frame(10, 10)
    service = MarketVolatilityAlertService(tmp_path, fetcher=slow_fetch, fetch_timeout_seconds=.001)
    result = service.check()
    assert result["last_check"]["status"] == "FAILED"
    assert len(result["failures"]) == 4
    assert all("timed out" in item["error"] for item in result["failures"])


def test_cache_avoids_a_second_network_fetch_for_five_minutes(tmp_path):
    calls: list[str] = []
    def fetch(code: str): calls.append(code); return frame(10, 10)
    service = MarketVolatilityAlertService(tmp_path, fetcher=fetch, now=lambda: datetime(2026, 8, 19, 22, tzinfo=UTC))
    assert len(service.check()["readings"]) == 4
    assert len(calls) == 4
    again = service.check()
    assert len(calls) == 4
    assert {item["source"] for item in again["readings"]} == {"CACHE"}


def test_current_unclosed_new_york_day_is_excluded(tmp_path):
    data = pd.DataFrame({"date": ["2026-08-17", "2026-08-18", "2026-08-19"], "close": [10, 11, 20]})
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda _: data, now=lambda: datetime(2026, 8, 19, 18, tzinfo=UTC)) # 14:00 New York
    result = service.check()
    assert {item["date"] for item in result["readings"]} == {"2026-08-18"}


def test_yahoo_chart_response_is_parsed_without_an_api_key(monkeypatch, tmp_path):
    class Response:
        status_code = 200
        def json(self):
            return {"chart": {"result": [{"timestamp": [1787097600, 1787184000], "indicators": {"quote": [{"close": [20.0, 21.0]}]}}]}}
    monkeypatch.setattr("app.services.market_volatility_alerts.httpx.get", lambda *args, **kwargs: Response())
    service = MarketVolatilityAlertService(tmp_path)
    bars = service._fetch_yahoo_daily_bars("^VIX")
    assert list(bars.close) == [20.0, 21.0]
