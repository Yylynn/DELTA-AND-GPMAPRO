"""Configurable, causal trading replay for the new backtest laboratory."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BacktestRuleConfig:
    initial_capital: float = 100_000.0
    commission_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 5.0
    max_holding_bars: int = 60


def _finite(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


class BacktestRuleEngine:
    """One-position, long-only replay driven by the shared signal event stream."""

    def __init__(self, signals, config: BacktestRuleConfig | None = None):
        self.signals = signals
        self.config = config or BacktestRuleConfig()

    @staticmethod
    def _metrics(
        equity: list[dict],
        trades: list[dict],
        exposure_bars: int,
        initial_capital: float,
    ) -> dict:
        values = pd.Series([row["equity"] for row in equity], dtype=float)
        if values.empty:
            return {
                "total_return": 0.0,
                "annualized_return": None,
                "max_drawdown": 0.0,
                "annualized_volatility": None,
                "sharpe": None,
                "trade_count": 0,
                "win_rate": None,
                "average_trade_return": None,
                "profit_factor": None,
                "exposure_rate": 0.0,
            }
        values_with_initial = pd.concat([
            pd.Series([initial_capital], dtype=float),
            values,
        ], ignore_index=True)
        daily = values_with_initial.pct_change().dropna()
        peaks = values_with_initial.cummax()
        drawdown = values_with_initial / peaks - 1
        years = max(len(values) / 252, 1 / 252)
        annualized = (values.iloc[-1] / initial_capital) ** (1 / years) - 1
        volatility = float(daily.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 else None
        sharpe = (
            float(daily.mean() / daily.std(ddof=1) * math.sqrt(252))
            if len(daily) > 1 and daily.std(ddof=1) > 0
            else None
        )
        returns = [float(trade["net_return"]) for trade in trades]
        gains = sum(value for value in returns if value > 0)
        losses = -sum(value for value in returns if value < 0)
        profit_factor = gains / losses if losses > 0 else (None if gains == 0 else math.inf)
        return {
            "total_return": float(values.iloc[-1] / initial_capital - 1),
            "annualized_return": _finite(annualized),
            "max_drawdown": float(drawdown.min()),
            "annualized_volatility": _finite(volatility),
            "sharpe": _finite(sharpe),
            "trade_count": len(trades),
            "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
            "average_trade_return": sum(returns) / len(returns) if returns else None,
            "profit_factor": _finite(profit_factor),
            "exposure_rate": exposure_bars / len(equity),
        }

    @staticmethod
    def _fingerprint(dataset: dict, parameters: dict) -> str:
        payload = {
            "dataset_id": dataset["dataset_id"],
            "data_sha256": dataset.get("data_sha256"),
            "parameters": parameters,
            "engine": "BACKTEST_RULE_ENGINE_V1",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _drawdown_curve(
        equity: list[dict],
        benchmark: list[dict],
        initial_capital: float,
    ) -> list[dict]:
        strategy_values = pd.Series([row["equity"] for row in equity], dtype=float)
        benchmark_values = pd.Series([row["equity"] for row in benchmark], dtype=float)
        strategy_peaks = pd.concat([
            pd.Series([initial_capital], dtype=float), strategy_values,
        ], ignore_index=True).cummax().iloc[1:].reset_index(drop=True)
        benchmark_peaks = pd.concat([
            pd.Series([initial_capital], dtype=float), benchmark_values,
        ], ignore_index=True).cummax().iloc[1:].reset_index(drop=True)
        strategy_drawdown = strategy_values / strategy_peaks - 1
        benchmark_drawdown = benchmark_values / benchmark_peaks - 1
        return [
            {
                "date": row["date"],
                "strategy_drawdown": float(strategy_drawdown.iloc[index]),
                "benchmark_drawdown": float(benchmark_drawdown.iloc[index]),
            }
            for index, row in enumerate(equity)
        ]

    @staticmethod
    def _monthly_returns(
        equity: list[dict],
        benchmark: list[dict],
        initial_capital: float,
    ) -> list[dict]:
        def monthly(curve: list[dict]) -> dict[str, float]:
            frame = pd.DataFrame(curve)
            frame["month"] = pd.to_datetime(frame.date).dt.to_period("M").astype(str)
            closes = frame.groupby("month", sort=True).equity.last()
            previous = closes.shift(1).fillna(initial_capital)
            return (closes / previous - 1).astype(float).to_dict()

        strategy = monthly(equity)
        reference = monthly(benchmark)
        return [
            {
                "month": month,
                "strategy_return": float(strategy[month]),
                "benchmark_return": float(reference[month]),
                "excess_return": float(strategy[month] - reference[month]),
            }
            for month in strategy
        ]

    @staticmethod
    def _trade_analysis(trades: list[dict]) -> dict:
        if not trades:
            return {
                "best_trade": None,
                "worst_trade": None,
                "average_holding_bars": None,
                "average_win": None,
                "average_loss": None,
                "payoff_ratio": None,
                "max_consecutive_losses": 0,
                "exit_reason_counts": {"SELL_SIGNAL": 0, "MAX_HOLD": 0},
            }
        returns = [float(trade["net_return"]) for trade in trades]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value < 0]
        average_win = sum(wins) / len(wins) if wins else None
        average_loss = sum(losses) / len(losses) if losses else None
        payoff = average_win / abs(average_loss) if average_win is not None and average_loss else None
        streak = longest = 0
        for value in returns:
            streak = streak + 1 if value < 0 else 0
            longest = max(longest, streak)
        reasons = {"SELL_SIGNAL": 0, "MAX_HOLD": 0}
        for trade in trades:
            reason = str(trade["exit_reason"])
            reasons[reason] = reasons.get(reason, 0) + 1
        return {
            "best_trade": max(trades, key=lambda trade: float(trade["net_return"])),
            "worst_trade": min(trades, key=lambda trade: float(trade["net_return"])),
            "average_holding_bars": sum(int(trade["holding_bars"]) for trade in trades) / len(trades),
            "average_win": _finite(average_win),
            "average_loss": _finite(average_loss),
            "payoff_ratio": _finite(payoff),
            "max_consecutive_losses": longest,
            "exit_reason_counts": reasons,
        }

    def run(
        self,
        dataset_id: str,
        *,
        buy_signals: list[str],
        sell_signals: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
        initial_capital: float | None = None,
        commission_bps_per_side: float | None = None,
        slippage_bps_per_side: float | None = None,
        max_holding_bars: int | None = None,
    ) -> dict:
        if not buy_signals:
            raise ValueError("select at least one buy signal")
        if not sell_signals:
            raise ValueError("select at least one sell signal")

        capital = self.config.initial_capital if initial_capital is None else initial_capital
        commission_bps = (
            self.config.commission_bps_per_side
            if commission_bps_per_side is None
            else commission_bps_per_side
        )
        slippage_bps = (
            self.config.slippage_bps_per_side
            if slippage_bps_per_side is None
            else slippage_bps_per_side
        )
        max_hold = self.config.max_holding_bars if max_holding_bars is None else max_holding_bars
        if capital <= 0:
            raise ValueError("initial capital must be positive")
        if commission_bps < 0 or slippage_bps < 0:
            raise ValueError("trading costs cannot be negative")
        if max_hold < 1:
            raise ValueError("max holding bars must be positive")

        calculated, dataset, events, full_counts = self.signals.calculate_all(dataset_id)
        catalog = self.signals.describe_signals(full_counts)
        signal_directions = {item["code"]: item["direction"] for item in catalog}
        known = set(full_counts)
        requested = set(buy_signals) | set(sell_signals)
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError(f"unknown signal codes: {', '.join(unknown)}")
        invalid_buy = sorted(code for code in set(buy_signals) if signal_directions.get(code) != "BUY")
        invalid_sell = sorted(code for code in set(sell_signals) if signal_directions.get(code) != "SELL")
        if invalid_buy:
            raise ValueError(f"buy rules contain non-buy signals: {', '.join(invalid_buy)}")
        if invalid_sell:
            raise ValueError(f"sell rules contain non-sell signals: {', '.join(invalid_sell)}")

        data = calculated.sort_values("date").reset_index(drop=True)
        if len(data) < 2:
            raise ValueError("backtest dataset requires at least two bars")
        lower = pd.Timestamp(start_date) if start_date else data.date.iloc[0]
        upper = pd.Timestamp(end_date) if end_date else data.date.iloc[-1]
        if lower > upper:
            raise ValueError("start date must not be after end date")
        selected = data.loc[(data.date >= lower) & (data.date <= upper)].copy().reset_index(drop=True)
        if len(selected) < 2:
            raise ValueError("backtest range requires at least two bars")

        selected_dates = set(selected.date.dt.date.astype(str))
        executable: dict[str, list[dict]] = {}
        for event in events:
            tradable_on = event.get("tradable_on")
            if tradable_on and tradable_on in selected_dates:
                executable.setdefault(tradable_on, []).append(event)

        buy_set, sell_set = set(buy_signals), set(sell_signals)
        commission = commission_bps / 10_000
        slippage = slippage_bps / 10_000
        cash = float(capital)
        position: dict | None = None
        trades: list[dict] = []
        equity: list[dict] = []
        exposure_bars = 0

        for index, row in selected.iterrows():
            day = row.date.date().isoformat()
            day_events = executable.get(day, [])
            buy_events = [event for event in day_events if event["code"] in buy_set]
            sell_events = [event for event in day_events if event["code"] in sell_set]
            exited_today = False

            if position is not None:
                holding_bars = index - int(position["entry_index"])
                exit_reason = None
                triggers: list[str] = []
                if sell_events:
                    exit_reason = "SELL_SIGNAL"
                    triggers = sorted({event["code"] for event in sell_events})
                elif holding_bars >= max_hold:
                    exit_reason = "MAX_HOLD"
                if exit_reason:
                    exit_price = float(row.open) * (1 - slippage)
                    proceeds = float(position["shares"]) * exit_price * (1 - commission)
                    cash = proceeds
                    cost_amount = (
                        float(position["entry_commission"])
                        + float(position["shares"]) * exit_price * commission
                    )
                    gross_return = exit_price / float(position["entry_price"]) - 1
                    net_return = cash / float(position["starting_cash"]) - 1
                    observed = selected.iloc[int(position["entry_index"]): index + 1]
                    trades.append({
                        "symbol": dataset["symbol"],
                        "entry_signal_date": position["signal_date"],
                        "entry_date": position["entry_date"],
                        "exit_signal_date": max(
                            (event["confirmed_on"] or event["signal_date"] for event in sell_events),
                            default=None,
                        ),
                        "exit_date": day,
                        "entry_signals": position["entry_signals"],
                        "exit_signals": triggers,
                        "entry_price": float(position["entry_price"]),
                        "exit_price": exit_price,
                        "shares": float(position["shares"]),
                        "gross_return": gross_return,
                        "net_return": net_return,
                        "pnl": cash - float(position["starting_cash"]),
                        "cost_amount": cost_amount,
                        "holding_bars": holding_bars,
                        "mfe": float(observed.high.max() / float(position["entry_price"]) - 1),
                        "mae": float(observed.low.min() / float(position["entry_price"]) - 1),
                        "exit_reason": exit_reason,
                    })
                    position = None
                    exited_today = True

            if position is None and not exited_today and buy_events:
                entry_price = float(row.open) * (1 + slippage)
                starting_cash = cash
                shares = cash / (entry_price * (1 + commission))
                entry_commission = shares * entry_price * commission
                cash = 0.0
                position = {
                    "entry_index": index,
                    "entry_date": day,
                    "signal_date": max(event["confirmed_on"] or event["signal_date"] for event in buy_events),
                    "entry_signals": sorted({event["code"] for event in buy_events}),
                    "entry_price": entry_price,
                    "shares": shares,
                    "entry_commission": entry_commission,
                    "starting_cash": starting_cash,
                }

            marked = cash
            if position is not None:
                exposure_bars += 1
                marked += float(position["shares"]) * float(row.close)
            equity.append({
                "date": day,
                "equity": float(marked),
                "cash": float(cash),
                "in_position": position is not None,
            })

        open_position = None
        if position is not None:
            last = selected.iloc[-1]
            marked_value = float(position["shares"]) * float(last.close)
            open_position = {
                "symbol": dataset["symbol"],
                "entry_signal_date": position["signal_date"],
                "entry_date": position["entry_date"],
                "entry_signals": position["entry_signals"],
                "entry_price": float(position["entry_price"]),
                "shares": float(position["shares"]),
                "last_date": last.date.date().isoformat(),
                "last_close": float(last.close),
                "unrealized_return": marked_value / float(position["starting_cash"]) - 1,
                "unrealized_pnl": marked_value - float(position["starting_cash"]),
            }

        benchmark_start = float(selected.open.iloc[0])
        benchmark_curve = [
            {
                "date": row.date.date().isoformat(),
                "equity": float(capital * float(row.close) / benchmark_start),
            }
            for row in selected.itertuples(index=False)
        ]
        drawdown_curve = self._drawdown_curve(equity, benchmark_curve, capital)
        monthly_returns = self._monthly_returns(equity, benchmark_curve, capital)
        parameters = {
            "buy_signals": sorted(buy_set),
            "sell_signals": sorted(sell_set),
            "start_date": start_date or selected.date.iloc[0].date().isoformat(),
            "end_date": end_date or selected.date.iloc[-1].date().isoformat(),
            "initial_capital": capital,
            "commission_bps_per_side": commission_bps,
            "slippage_bps_per_side": slippage_bps,
            "max_holding_bars": max_hold,
        }
        return {
            "dataset": dataset,
            "parameters": parameters,
            "period": {
                "start": selected.date.iloc[0].date().isoformat(),
                "end": selected.date.iloc[-1].date().isoformat(),
                "bar_count": len(selected),
            },
            "run_fingerprint": self._fingerprint(dataset, parameters),
            "metrics": self._metrics(equity, trades, exposure_bars, capital),
            "benchmark_metrics": self._metrics(
                benchmark_curve,
                [],
                len(benchmark_curve),
                capital,
            ),
            "equity_curve": equity,
            "benchmark_curve": benchmark_curve,
            "drawdown_curve": drawdown_curve,
            "monthly_returns": monthly_returns,
            "closed_trades": trades,
            "trade_analysis": self._trade_analysis(trades),
            "open_position": open_position,
            "signal_counts": {code: full_counts[code] for code in sorted(requested)},
            "assumptions": {
                "position": "single long-only position; no pyramiding or same-open re-entry",
                "rule_logic": "any selected signal triggers its side of the rule",
                "execution": "signals execute only on their causal tradable_on session open",
                "entry": "all available cash is invested",
                "costs": "commission and adverse slippage are charged independently per side",
                "fallback_exit": "position exits at open after max_holding_bars when no sell rule triggers",
                "open_position": "an end-of-range open position is marked at the final close and is not counted as a closed trade",
                "benchmark": "same-period buy-and-hold from the first session open, before trading costs",
            },
        }
