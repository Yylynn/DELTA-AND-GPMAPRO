import pandas as pd

from app.services.signal_rule_research import PROTOCOL_ID, SignalRuleResearchService, SignalRuleSpec


def _frame(version: str, n: int = 55) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=n)
    data = pd.DataFrame({"date": dates, "open": range(100, 100 + n), "high": range(101, 101 + n), "low": range(99, 99 + n), "close": range(100, 100 + n), "volume": 1000})
    names = (["b1", "b2", "b3", "bottom_face", "bottom_2", "bottom_3", "top_face", "top_2", "top_3", "s1", "s2"] if version == "1.0" else ["b01", "b02", "b03", "b11", "b12", "b3", "b4", "s01", "s02", "s11", "s12", "s2", "s22", "bottom_1", "bottom_2", "top_1", "top_2"])
    for name in names:
        data[name] = False
    data.loc[[i for i in [5, 16, 27, 38, 49] if i < n], names[0]] = True
    data["delta_low"] = False; data.loc[[i for i in [5, 16, 27, 38] if i < n], "delta_low"] = True
    data["delta_high"] = False
    return data


def test_protocol_uses_next_open_and_marks_unfinished_trade_open(monkeypatch):
    service = SignalRuleResearchService(bootstrap_samples=20)
    frames = {"1.0": _frame("1.0"), "2.0": _frame("2.0")}
    monkeypatch.setattr(service, "_features", lambda bars, version: (frames[version].copy(), []))
    result = service.run({"SPY": frames["1.0"]})
    assert result["protocol_id"] == PROTOCOL_ID
    records = [row for row in result["single_signal"] if row["rule"]["indicator_version"] == "1.0" and row["rule"]["entry_anchor"] == "B1" and row["rule"]["holding_days"] == 1]
    assert records
    signals = service._signal_map(frames["1.0"], "1.0")
    spec = SignalRuleSpec("1.0", "B1", holding_days=5)
    trades = service._trades(frames["1.0"], "SPY", spec, signals, stateful=False)
    assert trades[0]["entry_date"] == frames["1.0"].date.iloc[6].date().isoformat()  # T+1 open, never T close
    assert trades[-1]["open"] is True  # end_date/bars cannot manufacture a completed return


def test_delta_lookback_is_bounded_and_clustered():
    service = SignalRuleResearchService(bootstrap_samples=10)
    data = _frame("1.0", 12)
    data["b1"] = False; data.loc[[4, 5], "b1"] = True  # one displayed icon cluster
    data["delta_low"] = False; data.loc[2, "delta_low"] = True
    signals = service._signal_map(data, "1.0")
    one = service._trades(data, "SPY", SignalRuleSpec("1.0", "B1", "LOW", 1, holding_days=1), signals, stateful=False)
    two = service._trades(data, "SPY", SignalRuleSpec("1.0", "B1", "LOW", 2, holding_days=1), signals, stateful=False)
    assert one == []
    assert len(two) == 1
