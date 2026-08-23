"""Causal, descriptive volume facts for the research terminal."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config.volume_config import VOLUME_CONFIG, VolumeConfig
from app.services.data_freshness import freshness_snapshot


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}


def add_volume_metrics(bars: pd.DataFrame) -> pd.DataFrame:
    """Add the canonical MA/RVOL columns, using only each row's history."""
    data = bars.copy()
    volume = pd.to_numeric(data["volume"], errors="coerce")
    data["volume_ma5"] = volume.rolling(5, min_periods=1).mean()
    data["volume_ma20"] = volume.rolling(20, min_periods=1).mean()
    data["volume_ratio_5"] = np.where(data.volume_ma5 > 0, volume / data.volume_ma5, np.nan)
    data["volume_ratio_20"] = np.where(data.volume_ma20 > 0, volume / data.volume_ma20, np.nan)
    data["relative_volume"] = data["volume_ratio_20"]
    return data


class VolumeMonitor:
    def __init__(self, config: VolumeConfig = VOLUME_CONFIG): self.config = config

    def calculate(self, bars: pd.DataFrame, as_of: str | None = None) -> pd.DataFrame:
        if not REQUIRED_COLUMNS.issubset(bars.columns): raise ValueError("Volume Monitor requires OHLCV columns")
        data = bars.copy().sort_values("date").reset_index(drop=True); data["date"] = pd.to_datetime(data.date)
        if as_of: data = data[data.date <= pd.Timestamp(as_of)].copy().reset_index(drop=True)
        if data.empty: raise ValueError("No OHLCV data is available at as_of")
        if data[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").isna().any().any(): raise ValueError("Volume Monitor received invalid OHLCV data")
        return add_volume_metrics(data)

    def snapshot(self, bars: pd.DataFrame, symbol: str, timeframe: str, as_of: str | None = None) -> dict:
        data = self.calculate(bars, as_of); row = data.iloc[-1]; previous = data.iloc[-2] if len(data) > 1 else None; rvol = float(row.relative_volume)
        if not np.isfinite(rvol): raise ValueError("Volume Monitor requires a positive volume baseline")
        level = "VERY_LOW" if rvol < self.config.very_low_rvol else "LOW" if rvol < self.config.low_rvol else "NORMAL" if rvol < self.config.high_rvol else "HIGH" if rvol < self.config.very_high_rvol else "VERY_HIGH"
        ma_ratio = float(row.volume_ma5 / row.volume_ma20) if row.volume_ma20 else np.nan
        trend = "EXPANDING" if ma_ratio >= self.config.expanding_ratio else "CONTRACTING" if ma_ratio <= self.config.contracting_ratio else "STABLE"
        anomaly = "SPIKE" if rvol >= self.config.spike_rvol else "DRY_UP" if rvol <= self.config.dry_up_rvol else "NONE"
        price_change = None if previous is None or not previous.close else float((row.close / previous.close - 1) * 100)
        volume_change = None if previous is None or not previous.volume else float((row.volume / previous.volume - 1) * 100)
        direction = "UP" if price_change is not None and price_change > 0 else "DOWN" if price_change is not None and price_change < 0 else "FLAT"
        context = "UP_ON_HIGH_VOLUME" if direction == "UP" and rvol >= self.config.high_rvol else "UP_ON_LOW_VOLUME" if direction == "UP" and rvol < self.config.low_rvol else "DOWN_ON_HIGH_VOLUME" if direction == "DOWN" and rvol >= self.config.high_rvol else "DOWN_ON_LOW_VOLUME" if direction == "DOWN" and rvol < self.config.low_rvol else "NEUTRAL"
        freshness_as_of = pd.Timestamp(as_of).date() if as_of else None
        return {"symbol": symbol.upper(), "timeframe": timeframe, "as_of": row.date.date().isoformat(), "latest_volume": float(row.volume), "volume_ma5": float(row.volume_ma5), "volume_ma20": float(row.volume_ma20), "volume_ratio_5": float(row.volume_ratio_5) if np.isfinite(row.volume_ratio_5) else None, "volume_ratio_20": float(row.volume_ratio_20) if np.isfinite(row.volume_ratio_20) else None, "relative_volume": rvol, "volume_level": level, "volume_trend": trend, "volume_anomaly": anomaly, "price_change_pct": price_change, "volume_change_pct": volume_change, "price_direction": direction, "price_volume_context": context, "data": freshness_snapshot(row.date.date(), len(data), freshness_as_of)}

    def series(self, bars: pd.DataFrame, as_of: str | None = None) -> list[dict]:
        data = self.calculate(bars, as_of)
        return [{"date": row.date.date().isoformat(), "volume": float(row.volume), "volume_ma5": float(row.volume_ma5), "volume_ma20": float(row.volume_ma20), "relative_volume": float(row.relative_volume) if np.isfinite(row.relative_volume) else None} for row in data.itertuples(index=False)]
