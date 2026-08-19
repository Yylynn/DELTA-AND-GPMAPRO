"""Conservative fixed-horizon portfolio replay for the validated signal family."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from app.services.signal_backtest import SignalBacktestService


@dataclass(frozen=True)
class PortfolioBacktestConfig:
    initial_capital: float = 100_000.0
    horizon: int = 10
    cost_bps_per_side: float = 10.0


class PortfolioBacktestService:
    """Long-only, cash-constrained replay of DELTA_LOW_X_B signals.

    Signals are evaluated after the signal-day close and capital is split equally
    across every eligible new trade.  This is intentionally not a broker model.
    """
    strategy = "DELTA_LOW_X_B"

    def __init__(self, config: PortfolioBacktestConfig = PortfolioBacktestConfig()):
        self.config, self.signals = config, SignalBacktestService()

    @staticmethod
    def _metrics(equity: list[dict]) -> dict:
        if not equity:
            return {"total_return": 0.0, "max_drawdown": 0.0, "annualized_return": None, "annualized_volatility": None, "sharpe": None}
        values = pd.Series([x["equity"] for x in equity], dtype=float)
        daily = values.pct_change().dropna(); peaks = values.cummax(); drawdown = values / peaks - 1
        years = max(len(values) / 252, 1 / 252); annualized = (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1
        volatility = float(daily.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 else None
        sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 and daily.std(ddof=1) > 0 else None
        return {"total_return": float(values.iloc[-1] / values.iloc[0] - 1), "max_drawdown": float(drawdown.min()), "annualized_return": float(annualized), "annualized_volatility": volatility, "sharpe": sharpe}

    def run(self, bars_by_symbol: dict[str, pd.DataFrame], *, horizon: int | None = None, cost_bps: float | None = None, initial_capital: float | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
        horizon, cost, capital = horizon or self.config.horizon, self.config.cost_bps_per_side if cost_bps is None else cost_bps, initial_capital or self.config.initial_capital
        prepared = {}
        for symbol, raw in bars_by_symbol.items():
            data = raw.copy().sort_values("date").reset_index(drop=True); data["date"] = pd.to_datetime(data.date)
            flags = self.signals._signals(data)
            prepared[symbol.upper()] = (data, flags[self.strategy])
        calendar = sorted({day for data, _ in prepared.values() for day in data.date})
        lower = pd.Timestamp(start_date) if start_date else calendar[0]; upper = pd.Timestamp(end_date) if end_date else calendar[-1]
        cash, positions, trades, equity = capital, [], [], []
        for day in calendar:
            if day < lower or day > upper: continue
            exiting = [p for p in positions if p["exit_date"] == day]
            for position in exiting:
                data, _ = prepared[position["symbol"]]; row = data[data.date == day].iloc[0]; exit_price = float(row.open); proceeds = position["shares"] * exit_price * (1 - cost / 10_000); cash += proceeds
                trades.append({**position, "exit_price": exit_price, "gross_return": exit_price / position["entry_price"] - 1, "net_return": proceeds / position["notional"] - 1})
            positions = [p for p in positions if p["exit_date"] != day]
            candidates = []
            for symbol, (data, flags) in prepared.items():
                index = data.index[data.date == day]
                if not len(index): continue
                i = int(index[0])
                signal_index = i - 1
                if signal_index >= 0 and flags.iloc[signal_index] and i + horizon < len(data) and not any(p["symbol"] == symbol for p in positions): candidates.append((symbol, data, i, signal_index))
            allocation = cash / len(candidates) if candidates else 0
            for symbol, data, i, signal_index in candidates:
                price = float(data.open.iloc[i]); notional = allocation; shares = notional * (1 - cost / 10_000) / price
                cash -= notional; positions.append({"symbol": symbol, "signal_known_at": data.date.iloc[signal_index].date().isoformat(), "entry_date": day.date().isoformat(), "exit_date": data.date.iloc[i + horizon], "entry_price": price, "shares": shares, "notional": notional})
            marked = cash
            for position in positions:
                data, _ = prepared[position["symbol"]]; row = data[data.date == day]
                marked += position["shares"] * float(row.close.iloc[0]) if len(row) else position["notional"]
            equity.append({"date": day.date().isoformat(), "equity": marked, "cash": cash, "open_positions": len(positions)})
        benchmark = []
        if equity:
            first_day, last_day = pd.Timestamp(equity[0]["date"]), pd.Timestamp(equity[-1]["date"])
            entries = {}
            for symbol, (data, _) in prepared.items():
                available = data[data.date >= first_day]
                if len(available): entries[symbol] = float(available.iloc[0].close)
            for row in equity:
                day, returns = pd.Timestamp(row["date"]), []
                for symbol, (data, _) in prepared.items():
                    available = data[data.date <= day]
                    if symbol in entries and len(available): returns.append(float(available.iloc[-1].close) / entries[symbol] - 1)
                benchmark.append({"date": row["date"], "equity": capital * (1 + sum(returns) / len(returns)) if returns else capital})
        # Mark remaining positions at the final available close; they are labelled
        # open and excluded from closed-trade return statistics.
        return {"strategy": self.strategy, "initial_capital": capital, "horizon": horizon, "cost_bps_per_side": cost, "equity_curve": equity, "benchmark_curve": benchmark, "closed_trades": trades, "open_positions": [{**p, "exit_date": pd.Timestamp(p["exit_date"]).date().isoformat()} for p in positions], "metrics": self._metrics(equity), "benchmark_metrics": self._metrics(benchmark), "assumptions": {"portfolio": "long-only cash-constrained", "signal": "confirmation-day close", "entry": "next-session open", "allocation": "equal cash across new eligible signals", "exit": "fixed-horizon session open", "benchmark": "same-period equal-weight buy-and-hold across supplied symbols"}}
