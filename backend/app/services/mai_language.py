"""Small, causal MaiLanguage primitive runtime used by GPMAPRO.

This is deliberately a *calculation* runtime, not a permissive script engine.
The supplied formula stays reviewed Python, while the language operations with
subtle time-series semantics live in one testable place.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def _series(value: pd.Series | float | bool, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index)
    return pd.Series(value, index=index)


@dataclass
class MaiRuntime:
    """Evaluate causal MaiLanguage primitives and retain named trace columns."""

    index: pd.Index
    trace: dict[str, pd.Series] = field(default_factory=dict)

    def put(self, name: str, value: pd.Series | float | bool) -> pd.Series:
        result = _series(value, self.index)
        self.trace[name] = result
        return result

    def ema(self, value: pd.Series, period: int, name: str) -> pd.Series:
        return self.put(name, value.ewm(span=period, adjust=False, min_periods=1).mean())

    def ma(self, value: pd.Series, period: int, name: str) -> pd.Series:
        # Futu's MA emits DRAWNULL until a complete lookback window exists.
        return self.put(name, value.rolling(period, min_periods=period).mean())

    def ref(self, value: pd.Series, offset: int | pd.Series, name: str) -> pd.Series:
        if isinstance(offset, int):
            return self.put(name, value.shift(offset))
        result: list[float] = []
        for i, amount in enumerate(offset.reindex(self.index)):
            if pd.isna(amount):
                result.append(np.nan)
                continue
            target = i - int(amount)
            result.append(np.nan if target < 0 else value.iloc[target])
        return self.put(name, pd.Series(result, index=self.index, dtype="float64"))

    def barslast(self, condition: pd.Series, name: str) -> pd.Series:
        result: list[float] = []
        last: int | None = None
        for i, hit in enumerate(condition.reindex(self.index).fillna(False)):
            if bool(hit):
                last = i
            result.append(np.nan if last is None else i - last)
        return self.put(name, pd.Series(result, index=self.index, dtype="float64"))

    def count(self, condition: pd.Series, window: int, name: str) -> pd.Series:
        return self.put(name, condition.fillna(False).astype(int).rolling(window, min_periods=1).sum())

    def hhv(self, value: pd.Series, window: int | pd.Series, name: str) -> pd.Series:
        return self._extreme(value, window, name, maximum=True)

    def llv(self, value: pd.Series, window: int | pd.Series, name: str) -> pd.Series:
        return self._extreme(value, window, name, maximum=False)

    def _extreme(self, value: pd.Series, window: int | pd.Series, name: str, *, maximum: bool) -> pd.Series:
        if isinstance(window, int):
            result = value.rolling(window, min_periods=1).max() if maximum else value.rolling(window, min_periods=1).min()
            return self.put(name, result)
        result: list[float] = []
        for i, width in enumerate(window.reindex(self.index)):
            size = i + 1 if pd.isna(width) else max(1, int(width))
            values = value.iloc[max(0, i - size + 1): i + 1]
            result.append(values.max() if maximum else values.min())
        return self.put(name, pd.Series(result, index=self.index, dtype="float64"))

    def cross(self, left: pd.Series, right: pd.Series, name: str) -> pd.Series:
        return self.put(name, (left > right) & (left.shift(1) <= right.shift(1)))

    def drawnull(self, value: pd.Series, condition: pd.Series, name: str) -> pd.Series:
        """Keep the explicit discontinuity used by MaiLanguage drawing lines."""
        return self.put(name, value.where(condition))
