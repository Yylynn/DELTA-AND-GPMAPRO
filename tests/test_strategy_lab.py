import pandas as pd
import time

from app.services.strategy_lab import ENTRY_RULES, EXIT_RULES, StrategyLabService
from app.services.strategy_lab_runs import ForecastCache, StrategyLabRunStore


def bars(count=170):
    dates = pd.date_range("2023-01-02", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close - .5, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000})


def test_delta_forecasts_do_not_change_when_later_bars_are_mutated():
    service, source = StrategyLabService(), bars()
    before = service._features(source)[1]
    changed = source.copy()
    changed.loc[120:, ["open", "high", "low", "close", "volume"]] *= 5
    after = service._features(changed)[1]
    cutoff = source.date.iloc[100].date().isoformat()
    stable = lambda records: [(x["published_at"], x["event_type"], x["window_start"], x["window_end"]) for x in records if x["published_at"] <= cutoff]
    assert stable(before) == stable(after)


def test_signal_is_executed_at_the_next_open_and_exit_is_auditable():
    data = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=6, freq="B"),
        "open": [10, 11, 12, 13, 14, 15], "high": [11, 12, 13, 14, 15, 16], "low": [9, 10, 11, 12, 13, 14], "close": [10, 11, 12, 13, 14, 15],
        "s_signal": [False, False, True, False, False, False], "delta_high_window": [False] * 6, "top_divergence": [False] * 6,
        "delta_low_window": [False] * 6, "bottom_divergence": [False] * 6,
    })
    trade = StrategyLabService()._trade(data, "AAA", 0, "B_ONLY", "FIRST_S")
    assert trade is not None
    assert trade["entry_date"] == "2024-01-03"
    assert trade["entry_price"] == 11
    assert trade["exit_date"] == "2024-01-05"
    assert trade["exit_price"] == 13
    assert trade["exit_reason"] == "S"


def test_incomplete_fixed_horizon_trade_is_excluded_instead_of_forced_to_last_bar():
    data = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=6, freq="B"),
        "open": [10, 11, 12, 13, 14, 15], "high": [11, 12, 13, 14, 15, 16], "low": [9, 10, 11, 12, 13, 14], "close": [10, 11, 12, 13, 14, 15],
        "s_signal": [False] * 6, "delta_high_window": [False] * 6, "top_divergence": [False] * 6,
        "delta_low_window": [False] * 6, "bottom_divergence": [False] * 6,
    })
    assert StrategyLabService()._trade(data, "AAA", 0, "B_ONLY", "FIXED_5") is None


def test_strategy_matrix_is_pre_registered_and_fingerprinted():
    result = StrategyLabService().run({"AAA": bars()})
    assert len(result["strategies"]) == len(ENTRY_RULES) * len(EXIT_RULES)
    assert result["run_metadata"]["execution"] == "signal-day close; next-trading-day open"
    assert result["run_metadata"]["fingerprint"]
    assert all(item["research_assessment"]["label"] != "WORTH_CONTINUING" for item in result["strategies"])


def test_forecast_cache_is_bound_to_its_immutable_key(tmp_path):
    cache = ForecastCache(tmp_path / "cache")
    cache.put("snapshot:hash:formula", [{"published_at": "2024-01-02"}])
    assert cache.get("snapshot:hash:formula") == [{"published_at": "2024-01-02"}]
    assert cache.get("different-snapshot:hash:formula") is None


def test_research_run_reuses_identical_fingerprint_and_persists_result(tmp_path):
    store = StrategyLabRunStore(tmp_path / "runs")
    request, snapshots = {"symbols": ["US.SPY", "US.QQQ"]}, {"US.SPY": {"snapshot_id": "spy", "data_sha256": "1"}, "US.QQQ": {"snapshot_id": "qqq", "data_sha256": "2"}}
    def runner(progress):
        progress({"stage": "delta_replay", "progress": .5, "symbol": "US.SPY", "completed_symbols": 0, "total_symbols": 2})
        return {"strategies": []}
    first = store.create_or_reuse(request, snapshots, runner)
    second = store.create_or_reuse(request, snapshots, runner)
    assert first["run_id"] == second["run_id"]
    for _ in range(30):
        if store.status(first["run_id"])["status"] == "COMPLETED":
            break
        time.sleep(.02)
    assert store.result(first["run_id"]) == {"strategies": []}
