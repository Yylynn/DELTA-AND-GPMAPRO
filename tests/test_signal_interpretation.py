from datetime import date, timedelta

import pandas as pd
import pytest

from app.services.signal_interpretation import GPMA1_BEARISH, GPMA1_BULLISH, GPMA2_BEARISH, GPMA2_BULLISH, SignalInterpretationService


def _frame() -> pd.DataFrame:
    dates = pd.to_datetime([date.today() - timedelta(days=1), date.today()])
    frame = pd.DataFrame({"date": dates, "ema_20": [10.0, 11.0], "ema_60": [9.0, 10.0]})
    for column in [*GPMA1_BULLISH, *GPMA1_BEARISH, *GPMA2_BULLISH, *GPMA2_BEARISH, "top_face", "bottom_face", "top_2", "bottom_2", "top_3", "bottom_3", "top_1", "bottom_1"]:
        frame[column] = False
    frame["vol_ok"] = True; frame["gap_ok"] = True; frame["range_ok"] = True
    return frame


class _Engine:
    def __init__(self, frame: pd.DataFrame): self.frame = frame
    def calculate(self, bars: pd.DataFrame): return self.frame.iloc[:len(bars)].copy()


def test_confirmed_delta_low_plus_b_signal_is_research_long_candidate(monkeypatch):
    gpma1, gpma2 = _frame(), _frame()
    gpma1.loc[1, "b1"] = True
    service = SignalInterpretationService()
    service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", "script-hash"))
    monkeypatch.setattr(service, "_delta", lambda data: {"status": "READY", "direction": "BULLISH", "reversal_state": "NORMAL", "active_windows": [{"event_id": "low-1", "event_type": "LOW", "direction": "BULLISH", "actual_date": data.date.iloc[-1].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "active": True}]})
    bars = pd.DataFrame({"date": gpma1.date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    result = service.interpret(bars, "US.TEST", "1d", {"snapshot_id": "SNAPSHOT_A"})
    assert result["state"] == "POTENTIAL_LONG"
    assert result["research_only"] is True
    assert result["snapshot"]["snapshot_id"] == "SNAPSHOT_A"
    assert any(item["label"] == "B1" for item in result["evidence"])


def test_as_of_excludes_future_signal_and_delta(monkeypatch):
    gpma1, gpma2 = _frame(), _frame()
    gpma1.loc[1, "b1"] = True
    service = SignalInterpretationService()
    service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("UNAVAILABLE", None))
    monkeypatch.setattr(service, "_delta", lambda _data: {"status": "READY", "direction": "NEUTRAL", "reversal_state": "NORMAL", "active_windows": []})
    bars = pd.DataFrame({"date": gpma1.date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    result = service.interpret(bars, "US.TEST", "1d", {}, as_of=gpma1.date.iloc[0].date().isoformat())
    assert result["state"] == "NO_SETUP"
    assert not result["indicators"][0]["bullish_signals"]


def test_action_levels_keep_gpma2_fallback_from_becoming_a_trade_signal(monkeypatch):
    gpma1, gpma2 = _frame(), _frame()
    gpma2.loc[1, "b4"] = True
    service = SignalInterpretationService()
    service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", None))
    monkeypatch.setattr(service, "_delta", lambda _data: {"status": "READY", "direction": "NEUTRAL", "reversal_state": "NORMAL", "active_windows": []})
    bars = pd.DataFrame({"date": gpma1.date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    assert service.interpret(bars, "US.TEST", "1d", {})["action"] == "HOLD"


def test_action_buy_and_sell_require_stable_gpma_and_confirmed_delta(monkeypatch):
    bars = pd.DataFrame({"date": _frame().date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    def run(signal: str, delta_direction: str, bearish_trend: bool = False, volume_confirmed: bool = True):
        gpma1, gpma2 = _frame(), _frame()
        gpma1.loc[1, signal] = True
        gpma1["vol_ok"] = volume_confirmed
        if bearish_trend: gpma1["ema_20"] = [9.0, 9.0]; gpma1["ema_60"] = [10.0, 10.0]
        service = SignalInterpretationService(); service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
        monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", None))
        event_type = "LOW" if delta_direction == "BULLISH" else "HIGH"
        monkeypatch.setattr(service, "_delta", lambda data: {"status": "READY", "direction": delta_direction, "reversal_state": "NORMAL", "active_windows": [{"event_id": "event", "event_type": event_type, "direction": delta_direction, "actual_date": data.date.iloc[-1].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "active": True}]})
        return service.interpret(bars, "US.TEST", "1d", {})["action"]
    assert run("b1", "BULLISH") == "BUY"
    assert run("b1", "BULLISH", volume_confirmed=False) == "ACCUMULATE"
    assert run("s1", "BEARISH") == "REDUCE"
    assert run("s1", "BEARISH", bearish_trend=True) == "SELL"


def test_delta_action_window_starts_at_tradable_on_and_includes_tenth_bar(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=13, freq="B")
    data = pd.DataFrame({"date": dates, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100})

    class _Delta:
        def __init__(self, _config): pass
        def analyze(self, _data):
            return {"status": "READY", "reversal": {"state": "NORMAL"}, "confirmed_points": [{"id": "low", "type": "LOW", "date": dates[0].date().isoformat(), "actual_date": dates[0].date().isoformat(), "confirmed_on": dates[2].date().isoformat(), "tradable_on": dates[2].date().isoformat()}]}

    monkeypatch.setattr("app.services.signal_interpretation.ITDDeltaEngine", _Delta)
    active = SignalInterpretationService._delta(data)
    assert active["direction"] == "BULLISH"
    assert active["active_windows"][0]["bars_since"] == 10
    assert active["active_windows"][0]["delta_window_start"] == dates[2].date().isoformat()
    assert active["active_windows"][0]["delta_window_end"] == dates[12].date().isoformat()
    assert SignalInterpretationService._delta(pd.concat([data, data.iloc[[-1]].assign(date=dates[-1] + pd.offsets.BDay(1))], ignore_index=True))["direction"] == "NEUTRAL"


def test_historical_as_of_uses_as_of_as_freshness_reference(monkeypatch):
    dates = pd.to_datetime(["2020-01-02", "2020-01-03"])
    gpma1, gpma2 = _frame(), _frame()
    gpma1["date"] = dates; gpma2["date"] = dates; gpma1.loc[1, "b1"] = True
    service = SignalInterpretationService(); service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", None))
    monkeypatch.setattr(service, "_delta", lambda data: {"status": "READY", "direction": "BULLISH", "reversal_state": "NORMAL", "active_windows": [{"event_id": "low", "event_type": "LOW", "direction": "BULLISH", "actual_date": data.date.iloc[-1].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "delta_window_start": data.date.iloc[-1].date().isoformat(), "delta_window_end": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "action_eligible": True, "active": True}]})
    bars = pd.DataFrame({"date": dates, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    result = service.interpret(bars, "US.TEST", "1d", {}, as_of="2020-01-03")
    assert "行情快照不是当前数据，不能形成新的研究候选。" not in result["conflicts"]
    assert result["action"] == "BUY"


def test_gpma2_fallback_does_not_veto_stable_long_candidate(monkeypatch):
    gpma1, gpma2 = _frame(), _frame()
    gpma1.loc[1, "b1"] = True; gpma2.loc[1, "s01"] = True
    service = SignalInterpretationService(); service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", None))
    monkeypatch.setattr(service, "_delta", lambda data: {"status": "READY", "direction": "BULLISH", "reversal_state": "NORMAL", "active_windows": [{"event_id": "low", "event_type": "LOW", "direction": "BULLISH", "actual_date": data.date.iloc[-1].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "delta_window_start": data.date.iloc[-1].date().isoformat(), "delta_window_end": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "action_eligible": True, "active": True}]})
    bars = pd.DataFrame({"date": gpma1.date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    assert service.interpret(bars, "US.TEST", "1d", {})["action"] == "BUY"


@pytest.mark.parametrize(("signal", "bearish_trend", "expected"), [
    ("s01", False, "REDUCE"), ("s02", False, "HOLD"),
    ("s11", True, "REDUCE"), ("s12", False, "REDUCE"),
    ("s2", True, "REDUCE"), ("s22", False, "REDUCE"),
])
def test_gpma2_fallback_sell_signal_tiers(monkeypatch, signal, bearish_trend, expected):
    gpma1, gpma2 = _frame(), _frame()
    gpma2.loc[1, signal] = True
    if bearish_trend:
        gpma1["ema_20"] = [9.0, 9.0]; gpma1["ema_60"] = [10.0, 10.0]
    service = SignalInterpretationService(); service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", None))
    monkeypatch.setattr(service, "_delta", lambda data: {"status": "READY", "direction": "BEARISH", "reversal_state": "NORMAL", "active_windows": [{"event_id": "high", "event_type": "HIGH", "direction": "BEARISH", "actual_date": data.date.iloc[-1].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "delta_window_start": data.date.iloc[-1].date().isoformat(), "delta_window_end": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "action_eligible": True, "active": True}]})
    bars = pd.DataFrame({"date": gpma1.date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    result = service.interpret(bars, "US.TEST", "1d", {}, _include_audit=False)
    assert result["action"] == expected
    assert any(item["signal_code"] == signal.upper() for item in result["signal_details"])
    assert result["action"] != "SELL"


def test_gpma2_s01_keeps_reduce_when_delta_low_conflicts(monkeypatch):
    gpma1, gpma2 = _frame(), _frame(); gpma2.loc[1, "s01"] = True
    service = SignalInterpretationService(); service.gpma1, service.gpma2 = _Engine(gpma1), _Engine(gpma2)
    monkeypatch.setattr(service, "_gpma2_authority", lambda *_: ("LOCAL_RENDERER_FALLBACK", None))
    monkeypatch.setattr(service, "_delta", lambda data: {"status": "READY", "direction": "CONFLICT", "reversal_state": "NORMAL", "active_windows": [{"event_id": "high", "event_type": "HIGH", "direction": "BEARISH", "actual_date": data.date.iloc[-2].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "delta_window_start": data.date.iloc[-1].date().isoformat(), "delta_window_end": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "action_eligible": True, "active": True}, {"event_id": "low", "event_type": "LOW", "direction": "BULLISH", "actual_date": data.date.iloc[-1].date().isoformat(), "confirmed_on": data.date.iloc[-1].date().isoformat(), "tradable_on": data.date.iloc[-1].date().isoformat(), "delta_window_start": data.date.iloc[-1].date().isoformat(), "delta_window_end": data.date.iloc[-1].date().isoformat(), "bars_since": 0, "action_eligible": True, "active": True}]})
    bars = pd.DataFrame({"date": gpma1.date, "open": [10, 10], "high": [11, 11], "low": [9, 9], "close": [10, 10], "volume": [100, 100]})
    result = service.interpret(bars, "US.TEST", "1d", {}, _include_audit=False)
    assert result["action"] == "REDUCE"
    assert any("反向 DELTA LOW" in item for item in result["blocked_by"])


def test_gpma2_opend_failure_keeps_local_renderer_fallback(monkeypatch):
    class _TraceClient:
        def calculate(self, *_args, **_kwargs): raise RuntimeError("OpenD unavailable")
    monkeypatch.setattr("app.services.signal_interpretation.FutuGpmaProTraceClient", _TraceClient)
    assert SignalInterpretationService._gpma2_authority(_frame(), "US.TEST", "1d") == ("LOCAL_RENDERER_FALLBACK", None)
