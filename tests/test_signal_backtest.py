import pandas as pd

from app.services.signal_backtest import SignalBacktestService
from app.services.portfolio_backtest import PortfolioBacktestService
from app.services.walk_forward import WalkForwardService


def bars(count=320):
    dates = pd.date_range("2023-01-02", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close - .5, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000})


def test_returns_are_cost_adjusted_and_horizon_bounded():
    result = SignalBacktestService().run_symbol(bars(), "AAPL", horizons=(5,), cost_bps=10)
    for group in result["groups"].values():
        stats = group["5"]
        if stats["sample_count"]:
            assert stats["average_net_return"] < stats["average_gross_return"]
    for trade in result["trades"]:
        assert trade["horizon"] == 5
        assert trade["entry_date"] > trade["signal_known_at"]


def test_trade_uses_next_open_for_entry_and_horizon_open_for_exit():
    data = bars(10)
    trade = SignalBacktestService()._trade(data, 1, "DELTA_LOW", 3, 10)
    assert trade is not None
    assert trade["signal_known_at"] == data.date.iloc[1].date().isoformat()
    assert trade["entry_date"] == data.date.iloc[2].date().isoformat()
    assert trade["entry_price"] == data.open.iloc[2]
    assert trade["exit_price"] == data.open.iloc[5]


def test_future_data_does_not_change_existing_signal_dates():
    service, source = SignalBacktestService(), bars()
    before = service.run_symbol(source, "AAPL", horizons=(5,), end_date="2023-10-02")
    mutated = source.copy(); mutated.loc[220:, ["open", "high", "low", "close", "volume"]] *= 5
    after = service.run_symbol(mutated, "AAPL", horizons=(5,), end_date="2023-10-02")
    assert [(x["date"], x["signal"]) for x in before["trades"] if x["date"] <= "2023-09-25"] == [(x["date"], x["signal"]) for x in after["trades"] if x["date"] <= "2023-09-25"]


def test_multi_symbol_summary_is_equal_weighted_and_fingerprinted():
    service = SignalBacktestService()
    first, second = bars(), bars(); second.loc[:, ["open", "high", "low", "close"]] *= 2
    result = service.run({"AAA": first, "BBB": second}, horizons=(5,))
    candidate = next(values["5"] for values in result["pooled"]["groups"].values() if values["5"]["sample_count"])
    assert candidate["aggregation"] == "EQUAL_WEIGHT_BY_SYMBOL"
    assert result["run_metadata"]["fingerprint"]
    assert len(candidate["net_return_ci_95"]) == 2


def test_run_metadata_binds_formula_and_immutable_data_provenance():
    provenance = {"source": "futu_opend_snapshot", "snapshot_id": "US_AAPL_1D_QFQ_TEST", "data_sha256": "abc"}
    result = SignalBacktestService().run({"AAPL": bars()}, horizons=(5,), data_provenance=provenance)
    assert result["run_metadata"]["formula"] == "JUSTIN_WEAPON"
    assert result["run_metadata"]["formula_sha256"]
    assert result["run_metadata"]["data_provenance"] == provenance


def test_portfolio_replay_is_cash_constrained_and_reports_risk_metrics():
    result = PortfolioBacktestService().run({"AAA": bars(), "BBB": bars()}, horizon=5, initial_capital=10_000)
    assert result["equity_curve"][0]["equity"] <= 10_000
    assert set(result["metrics"]) == {"total_return", "max_drawdown", "annualized_return", "annualized_volatility", "sharpe"}
    assert len(result["benchmark_curve"]) == len(result["equity_curve"])
    assert result["benchmark_metrics"]["total_return"] is not None
    assert all(trade["net_return"] < trade["gross_return"] for trade in result["closed_trades"])


def test_walk_forward_windows_are_ordered_and_deterministic():
    source = bars(420); service = WalkForwardService()
    first = service.run({"AAA": source}, horizon=5, cost_bps=10, min_history_bars=100, test_bars=40, step_bars=40)
    second = service.run({"AAA": source}, horizon=5, cost_bps=10, min_history_bars=100, test_bars=40, step_bars=40)
    assert first == second
    assert all(window["train_end"] < window["test_start"] <= window["test_end"] for window in first["windows"])
