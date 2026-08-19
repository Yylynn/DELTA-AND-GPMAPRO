import pandas as pd
from app.services.decision_diagnostics import DecisionDiagnostics
from app.services.decision_backtest import DecisionBacktestService


def bars(base, count=35):
    dates = pd.date_range("2025-01-01", periods=count, freq="B"); close = pd.Series(range(base, base + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close-.5, "high": close+1, "low": close-1, "close": close, "volume": [1000] * count})


def test_cross_symbol_diagnostics_has_pooled_per_symbol_and_funnel():
    out = DecisionDiagnostics().run({"AAA": bars(100), "BBB": bars(200)}, "1d", None, None, "TRANSITION")
    assert set(out["pooled"]) == {"BUY", "WATCH", "WAIT", "RISK"}
    assert set(out["per_symbol"]) == {"AAA", "BBB"}
    assert {"configured_events", "active_windows", "decision_confirmations", "zero_confirmation_reason"} <= set(out["delta_funnel"])
    assert {"buy_separation", "risk_separation", "confidence_calibration", "delta_coverage", "volume_incremental_value"} <= set(out["robustness_flags"])


def test_cross_symbol_is_deterministic_and_has_year_breakdown():
    service = DecisionDiagnostics(); data = {"AAA": bars(100), "BBB": bars(200)}
    first = service.run(data, "1d", None, None, "DAILY"); second = service.run(data, "1d", None, None, "DAILY")
    assert first == second and "2025" in first["yearly"]


def test_low_sample_symbols_are_excluded_from_breadth():
    per_symbol = {"A": {"BUY": {"sample_count_10": 4, "median_return_10": .1}}, "B": {"BUY": {"sample_count_10": 5, "median_return_10": -.1}}}
    cross = DecisionDiagnostics()._cross_state(per_symbol, "BUY")
    assert cross["eligible_symbols"] == 1 and cross["symbol_positive_breadth"] == 0
