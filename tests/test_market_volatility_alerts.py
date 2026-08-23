import time
from datetime import UTC, datetime

import pandas as pd

from app.services.market_volatility_alerts import MARKET_INDEX_TECHNICAL_INDICATORS, MarketVolatilityAlertService


def frame(previous: float, current: float) -> pd.DataFrame:
    return pd.DataFrame({"date": ["2026-08-17", "2026-08-18"], "close": [previous, current]})


def all_market_values(*, vix: pd.DataFrame | None = None, vxn: pd.DataFrame | None = None, vvix: pd.DataFrame | None = None, vixy: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    fallback = frame(20, 20)
    return {"^VIX": vix if vix is not None else fallback, "^VXN": vxn if vxn is not None else fallback, "^VVIX": vvix if vvix is not None else fallback, "VIXY": vixy if vixy is not None else fallback, **{item["code"]: fallback for item in MARKET_INDEX_TECHNICAL_INDICATORS}}


def test_daily_change_at_three_percent_creates_one_alert_and_deduplicates(tmp_path):
    values = all_market_values(vix=frame(20, 20.6))
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda code: values[code])
    first = service.check()
    assert [(item["label"], item["reason_kind"]) for item in first["created_alerts"]] == [("VIX", "DAILY_CHANGE"), ("VIX", "WATCH_LEVEL")]
    assert service.check()["created_alerts"] == []


def test_multiple_indicators_and_risk_level_are_reported(tmp_path):
    values = all_market_values(vix=frame(24, 25.2), vxn=frame(29, 30), vvix=frame(10, 10.3), vixy=frame(10, 10.3))
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
    assert len(result["failures"]) == 7
    assert all("timed out" in item["error"] for item in result["failures"])


def test_cache_avoids_a_second_network_fetch_for_five_minutes(tmp_path):
    calls: list[str] = []
    def fetch(code: str): calls.append(code); return frame(10, 10)
    service = MarketVolatilityAlertService(tmp_path, fetcher=fetch, now=lambda: datetime(2026, 8, 19, 22, tzinfo=UTC))
    assert len(service.check()["readings"]) == 4
    assert len(calls) == 7
    again = service.check()
    assert len(calls) == 7
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


def test_all_final_gpmapro_markers_become_deduplicated_technical_alerts(monkeypatch, tmp_path):
    dates = pd.date_range("2026-08-01", periods=80, freq="B")
    bars = pd.DataFrame({"date": dates, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1000})
    final_columns = ["b1", "b2", "b3", "s1", "s2", "top_face", "bottom_face", "top_2", "bottom_2", "top_3", "bottom_3"]
    calculated = pd.DataFrame({"date": dates, **{column: False for column in final_columns}})
    for column in final_columns: calculated.loc[calculated.index[-1], column] = True
    monkeypatch.setattr("app.services.market_volatility_alerts.GpmaProEngine.calculate", lambda self, _: calculated)
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda _: bars, now=lambda: datetime(2026, 12, 1, 22, tzinfo=UTC))
    result = service.check()
    technical = [item for item in result["created_alerts"] if item["category"] == "GPMAPRO_TECHNICAL"]
    assert {item["signal_code"] for item in technical} == {"B1", "B2", "B3", "S1", "S2", "顶部笑脸", "底部笑脸", "顶部二级箭头", "底部二级箭头", "顶部三级箭头", "底部三级箭头"}
    assert service.check()["created_alerts"] == []


def test_gpmapro_raw_only_conditions_are_never_alerted(monkeypatch, tmp_path):
    dates = pd.date_range("2026-08-01", periods=80, freq="B")
    bars = pd.DataFrame({"date": dates, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1000})
    calculated = pd.DataFrame({"date": dates, "b1": False, "b2": False, "b3": False, "s1": False, "s2": False, "top_face": False, "bottom_face": False, "top_2": False, "bottom_2": False, "top_3": False, "bottom_3": False, "top_1_raw": True})
    monkeypatch.setattr("app.services.market_volatility_alerts.GpmaProEngine.calculate", lambda self, _: calculated)
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda _: bars, now=lambda: datetime(2026, 12, 1, 22, tzinfo=UTC))
    assert not [item for item in service.check()["created_alerts"] if item["category"] == "GPMAPRO_TECHNICAL"]


def test_snapshot_exposes_only_latest_three_sessions_as_active_technical_alerts(tmp_path):
    service = MarketVolatilityAlertService(tmp_path)
    state = service._default_state()
    state["market_cache"] = {
        "vix": {"bars": [{"date": date, "close": 10.0} for date in ["2026-08-14", "2026-08-17", "2026-08-18", "2026-08-19"]]}
    }
    state["alerts"] = [
        {"id": "old-tech", "date": "2026-08-14", "signal_date": "2026-08-14", "category": "GPMAPRO_TECHNICAL"},
        {"id": "recent-tech", "date": "2026-08-17", "signal_date": "2026-08-17", "category": "GPMAPRO_TECHNICAL"},
        {"id": "risk-history", "date": "2026-08-14", "category": "VOLATILITY_LEVEL"},
    ]
    service._save(state)

    snapshot = service.snapshot()

    assert {item["id"] for item in snapshot["alerts"]} == {"old-tech", "recent-tech", "risk-history"}
    assert {item["id"] for item in snapshot["active_alerts"]} == {"recent-tech"}
    assert snapshot["technical_lookback_sessions"] == 3


def test_snapshot_hides_a_prior_session_rise_after_the_indicator_falls(tmp_path):
    service = MarketVolatilityAlertService(tmp_path)
    state = service._default_state()
    state["observations"] = [
        {"id": "vix", "date": "2026-08-20", "change_pct": 7.5},
        {"id": "vix", "date": "2026-08-21", "change_pct": -5.5},
    ]
    state["alerts"] = [
        {"id": "vix-rise", "indicator_id": "vix", "date": "2026-08-20", "category": "VOLATILITY_LEVEL"},
    ]
    service._save(state)

    snapshot = service.snapshot()

    assert snapshot["active_alerts"] == []
    assert [item["id"] for item in snapshot["alerts"]] == ["vix-rise"]


def test_market_indexes_emit_technical_signals_only_and_appear_in_dedicated_snapshot_group(monkeypatch, tmp_path):
    dates = pd.date_range("2026-08-01", periods=80, freq="B")
    bars = pd.DataFrame({"date": dates, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1000})
    calculated = pd.DataFrame({"date": dates, **{column: False for column in ["b1", "b2", "b3", "s1", "s2", "top_face", "bottom_face", "top_2", "bottom_2", "top_3", "bottom_3"]}})
    calculated.loc[calculated.index[-1], "b1"] = True
    monkeypatch.setattr("app.services.market_volatility_alerts.GpmaProEngine.calculate", lambda self, _: calculated)
    service = MarketVolatilityAlertService(tmp_path, fetcher=lambda _: bars, now=lambda: datetime(2026, 12, 1, 22, tzinfo=UTC))

    result = service.check()
    index_alerts = [item for item in result["created_alerts"] if item.get("asset_type") == "MARKET_INDEX"]
    snapshot = service.snapshot()

    assert {(item["label"], item["signal_code"]) for item in index_alerts} == {("标普 500", "B1"), ("纳斯达克 100", "B1"), ("纳斯达克综合指数", "B1")}
    assert all(item["reason_kind"] == "B1" and "指数上行技术信号" in item["message"] for item in index_alerts)
    assert {item["label"] for item in snapshot["market_index_technical_signals"]} == {"标普 500", "纳斯达克 100", "纳斯达克综合指数"}
    assert all(item["label"] not in {"标普 500", "纳斯达克 100", "纳斯达克综合指数"} for item in snapshot["technical_signals"])
