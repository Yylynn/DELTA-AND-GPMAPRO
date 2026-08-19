"""Walk-forward reporting for a fixed, non-optimised portfolio rule."""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from app.services.portfolio_backtest import PortfolioBacktestService


@dataclass(frozen=True)
class WalkForwardConfig:
    test_bars: int = 63
    step_bars: int = 63
    min_history_bars: int = 252


class WalkForwardService:
    def __init__(self, config: WalkForwardConfig = WalkForwardConfig(), portfolio: PortfolioBacktestService | None = None):
        self.config, self.portfolio = config, portfolio or PortfolioBacktestService()

    def run(self, bars_by_symbol: dict[str, pd.DataFrame], *, horizon: int, cost_bps: float, test_bars: int | None = None, step_bars: int | None = None, min_history_bars: int | None = None) -> dict:
        test, step, minimum = test_bars or self.config.test_bars, step_bars or self.config.step_bars, min_history_bars or self.config.min_history_bars
        if test <= 0 or step <= 0 or minimum <= 0: raise ValueError("walk-forward windows must be positive")
        frames = {symbol: data.copy().sort_values("date").reset_index(drop=True) for symbol, data in bars_by_symbol.items()}
        for data in frames.values(): data["date"] = pd.to_datetime(data.date)
        common = sorted(set.intersection(*[set(data.date) for data in frames.values()]))
        windows = []
        for start in range(minimum, len(common) - test + 1, step):
            test_dates = common[start:start + test]
            scoped = {symbol: data[data.date <= test_dates[-1]].copy() for symbol, data in frames.items()}
            result = self.portfolio.run(scoped, horizon=horizon, cost_bps=cost_bps, start_date=test_dates[0].date().isoformat(), end_date=test_dates[-1].date().isoformat())
            windows.append({"train_start": common[0].date().isoformat(), "train_end": common[start - 1].date().isoformat(), "test_start": test_dates[0].date().isoformat(), "test_end": test_dates[-1].date().isoformat(), "test_bars": len(test_dates), "closed_trades": len(result["closed_trades"]), "metrics": result["metrics"]})
        completed = [x for x in windows if x["closed_trades"]]
        positive = sum(x["metrics"]["total_return"] > 0 for x in completed)
        avg = lambda key: sum(float(x["metrics"][key]) for x in completed if x["metrics"][key] is not None) / len([x for x in completed if x["metrics"][key] is not None]) if any(x["metrics"][key] is not None for x in completed) else None
        average_sharpe = avg("sharpe")
        return {"strategy": self.portfolio.strategy, "parameters": {"test_bars": test, "step_bars": step, "min_history_bars": minimum, "horizon": horizon, "cost_bps_per_side": cost_bps}, "windows": windows, "summary": {"window_count": len(windows), "active_window_count": len(completed), "positive_window_rate": positive / len(completed) if completed else None, "average_test_return": avg("total_return"), "average_test_max_drawdown": avg("max_drawdown"), "average_test_sharpe": average_sharpe, "verdict": "INSUFFICIENT" if len(completed) < 4 else "PROMISING" if positive / len(completed) >= .6 and (average_sharpe or 0) > 0 else "NOT_ROBUST"}}
