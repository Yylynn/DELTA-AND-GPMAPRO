import csv
import io

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services.backtest_rule_engine import BacktestRuleEngine
from app.services.backtest_signal_preview import (
    BacktestSignalPreviewService,
    DELTA_SIGNALS,
    DIVERGENCE_SIGNALS,
)
from app.services.gpmaapro_engine import SIGNALS


ALL_CODES = (
    *(signal.upper() for signal in SIGNALS),
    *(code for code, _, _ in DIVERGENCE_SIGNALS),
    *DELTA_SIGNALS,
)


def bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=8)
    return pd.DataFrame({
        "date": dates,
        "open": [10, 11, 12, 13, 14, 15, 16, 17],
        "high": [11, 12, 13, 14, 15, 16, 17, 18],
        "low": [9, 10, 11, 12, 13, 14, 15, 16],
        "close": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5],
        "volume": 1_000,
    })


def event(code: str, direction: str, signal_index: int, trade_index: int) -> dict:
    frame = bars()
    signal_date = frame.date.iloc[signal_index].date().isoformat()
    tradable_on = frame.date.iloc[trade_index].date().isoformat()
    return {
        "code": code,
        "family": "B" if direction == "BUY" else "S",
        "direction": direction,
        "signal_date": signal_date,
        "marker_date": signal_date,
        "tradable_on": tradable_on,
        "actual_date": signal_date,
        "confirmed_on": signal_date,
        "price": 10.0,
        "structure_price": None,
    }


class FakeSignals:
    describe_signals = staticmethod(BacktestSignalPreviewService.describe_signals)

    def __init__(self, events: list[dict]):
        self.events = events

    def calculate_all(self, dataset_id: str):
        frame = bars()
        counts = {code: 0 for code in ALL_CODES}
        for item in self.events:
            counts[item["code"]] += 1
        dataset = {
            "dataset_id": dataset_id,
            "source": "local_csv",
            "symbol": "US.TEST",
            "timeframe": "1d",
            "bar_count": len(frame),
            "data_sha256": "abc",
        }
        return frame, dataset, self.events, counts, {"status": "READY"}


def test_rule_engine_executes_selected_signals_on_next_session_open():
    engine = BacktestRuleEngine(FakeSignals([
        event("B01", "BUY", 0, 1),
        event("S01", "SELL", 3, 4),
    ]))

    result = engine.run(
        "local_csv:US.TEST",
        buy_signals=["B01"],
        sell_signals=["S01"],
        initial_capital=100.0,
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        max_holding_bars=6,
    )

    trade = result["closed_trades"][0]
    assert trade["entry_signal_date"] == bars().date.iloc[0].date().isoformat()
    assert trade["entry_date"] == bars().date.iloc[1].date().isoformat()
    assert trade["exit_signal_date"] == bars().date.iloc[3].date().isoformat()
    assert trade["exit_date"] == bars().date.iloc[4].date().isoformat()
    assert trade["entry_price"] == 11
    assert trade["exit_price"] == 14
    assert trade["net_return"] == 14 / 11 - 1
    assert trade["exit_reason"] == "SELL_SIGNAL"
    assert result["metrics"]["trade_count"] == 1
    assert result["open_position"] is None
    assert len(result["drawdown_curve"]) == len(result["equity_curve"])
    assert result["monthly_returns"]
    assert result["trade_analysis"]["best_trade"]["entry_date"] == trade["entry_date"]
    assert result["trade_analysis"]["exit_reason_counts"]["SELL_SIGNAL"] == 1


def test_rule_engine_uses_max_holding_bars_as_a_causal_fallback():
    engine = BacktestRuleEngine(FakeSignals([event("B01", "BUY", 0, 1)]))

    result = engine.run(
        "local_csv:US.TEST",
        buy_signals=["B01"],
        sell_signals=["S01"],
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        max_holding_bars=2,
    )

    trade = result["closed_trades"][0]
    assert trade["exit_date"] == bars().date.iloc[3].date().isoformat()
    assert trade["exit_reason"] == "MAX_HOLD"
    assert trade["exit_signals"] == []


def test_rule_engine_charges_commission_and_adverse_slippage_per_side():
    engine = BacktestRuleEngine(FakeSignals([
        event("B01", "BUY", 0, 1),
        event("S01", "SELL", 3, 4),
    ]))
    free = engine.run(
        "local_csv:US.TEST",
        buy_signals=["B01"],
        sell_signals=["S01"],
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
    )
    costed = engine.run(
        "local_csv:US.TEST",
        buy_signals=["B01"],
        sell_signals=["S01"],
        commission_bps_per_side=10,
        slippage_bps_per_side=10,
    )

    assert costed["closed_trades"][0]["net_return"] < free["closed_trades"][0]["net_return"]
    assert costed["closed_trades"][0]["cost_amount"] > 0
    assert costed["run_fingerprint"] != free["run_fingerprint"]


def test_rule_engine_rejects_a_sell_signal_in_the_buy_rule():
    engine = BacktestRuleEngine(FakeSignals([]))

    try:
        engine.run(
            "local_csv:US.TEST",
            buy_signals=["S01"],
            sell_signals=["S02"],
        )
    except ValueError as error:
        assert "non-buy" in str(error)
    else:
        raise AssertionError("directionally invalid rules must be rejected")


def test_rule_engine_api_returns_auditable_result(monkeypatch):
    from app.api import backtest_datasets as dataset_api

    engine = BacktestRuleEngine(FakeSignals([
        event("BOTTOM_FACE", "BUY", 0, 1),
        event("TOP_FACE", "SELL", 3, 4),
    ]))
    monkeypatch.setattr(dataset_api, "rule_engine", engine)

    response = TestClient(app).post("/api/backtest/rules/run", json={
        "dataset_id": "local_csv:US.TEST",
        "buy_signals": ["BOTTOM_FACE"],
        "sell_signals": ["TOP_FACE"],
        "commission_bps_per_side": 0,
        "slippage_bps_per_side": 0,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["closed_trades"][0]["entry_signals"] == ["BOTTOM_FACE"]
    assert len(payload["run_fingerprint"]) == 64
    assert {"metrics", "equity_curve", "drawdown_curve", "monthly_returns", "closed_trades", "assumptions"} <= set(payload)


def test_rule_engine_csv_export_is_a_clear_operation_equity_ledger(monkeypatch):
    from app.api import backtest_datasets as dataset_api

    engine = BacktestRuleEngine(FakeSignals([
        event("B01", "BUY", 0, 1),
        event("S01", "SELL", 3, 4),
    ]))
    monkeypatch.setattr(dataset_api, "rule_engine", engine)
    request = {
        "dataset_id": "local_csv:US.TEST",
        "buy_signals": ["B01"],
        "sell_signals": ["S01"],
        "commission_bps_per_side": 0,
        "slippage_bps_per_side": 0,
    }
    client = TestClient(app)
    result = client.post("/api/backtest/rules/run", json=request).json()
    response = client.post("/api/backtest/rules/export.csv", json=request)

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "backtest-US-TEST" in response.headers["content-disposition"]
    assert response.headers["x-backtest-fingerprint"] == result["run_fingerprint"]
    exported = response.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(exported))
    rows = list(reader)
    assert reader.fieldnames == ["时间", "资金", "操作", "盈利/亏损"]
    assert len(rows) == len(result["equity_curve"])
    trade = result["closed_trades"][0]
    entry = next(row for row in rows if row["时间"] == trade["entry_date"])
    exit_row = next(row for row in rows if row["时间"] == trade["exit_date"])
    assert entry["操作"] == "买入 B01"
    assert entry["盈利/亏损"] == ""
    assert exit_row["操作"] == "卖出 S01"
    assert exit_row["盈利/亏损"] == f"{trade['pnl']:+.2f}"
