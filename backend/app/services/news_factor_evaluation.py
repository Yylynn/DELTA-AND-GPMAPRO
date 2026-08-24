"""Point-in-time evaluation of V3 news factors; never emits trading orders."""
from __future__ import annotations

from collections import Counter
from math import sqrt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.config.news_universe import SECTOR_BENCHMARK
from app.data.providers import CsvDataProvider


class NewsFactorEvaluationService:
    HORIZONS = (1, 3, 5)
    MINIMUM_SESSIONS = 60

    def __init__(self, snapshot_root: Path, price_root: Path, cost_bps: float = 10) -> None:
        self.snapshot_root, self.prices, self.cost_bps = snapshot_root, CsvDataProvider(price_root), cost_bps

    def _snapshots(self, as_of: str | None = None) -> list[dict[str, Any]]:
        rows = []
        cutoff = pd.Timestamp(as_of) if as_of else None
        if cutoff is not None and cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        for path in sorted(self.snapshot_root.glob("*.json")) if self.snapshot_root.exists() else []:
            try: payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): continue
            if payload.get("schema_version") != 3 or payload.get("quality_status") != "VALID": continue
            captured = pd.Timestamp(payload.get("captured_at"))
            if captured.tzinfo is None: captured = captured.tz_localize("UTC")
            if cutoff is None or captured <= cutoff: rows.append(payload)
        return sorted(rows, key=lambda item: str(item.get("captured_at", "")))

    def _price(self, symbol: str) -> pd.DataFrame | None:
        try:
            frame, _ = self.prices.ohlcv(symbol); frame["date"] = pd.to_datetime(frame["date"]); return frame.set_index("date")
        except (FileNotFoundError, ValueError): return None

    def _rows(self, as_of: str | None = None) -> list[dict[str, Any]]:
        output, cache = [], {}
        cutoff_date = None
        if as_of:
            cutoff = pd.Timestamp(as_of)
            cutoff_date = (cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
        for snapshot in self._snapshots(as_of):
            for symbol_code, feature in snapshot.get("features", {}).items():
                symbol = symbol_code.removeprefix("US."); trade_at = feature.get("earliest_trade_at")
                if not trade_at or not feature.get("data_quality", {}).get("valid_article_count"): continue
                if symbol not in cache: cache[symbol] = self._price(symbol)
                prices = cache[symbol]
                if prices is None: continue
                trade_date = pd.Timestamp(trade_at).tz_convert("America/New_York").tz_localize(None).normalize()
                positions = np.flatnonzero(prices.index >= trade_date)
                if not len(positions): continue
                start = int(positions[0]); row = {"snapshot_at": snapshot["captured_at"], "session_date": snapshot.get("session_date"), "month": trade_date.strftime("%Y-%m"), "symbol": symbol, "score": float(feature.get("factor_score", feature.get("baseline_score", 0))), "trade_date": trade_date}
                for horizon in self.HORIZONS:
                    if start + horizon >= len(prices): continue
                    if cutoff_date is not None and prices.index[start + horizon] > cutoff_date: continue
                    row[f"return_{horizon}d"] = float(prices.close.iloc[start + horizon] / prices.open.iloc[start] - 1)
                    for label, benchmark in (("spy_excess", "SPY"), ("sector_excess", SECTOR_BENCHMARK.get(symbol))):
                        if not benchmark: continue
                        if benchmark not in cache: cache[benchmark] = self._price(benchmark)
                        benchmark_prices = cache[benchmark]
                        if benchmark_prices is None: continue
                        benchmark_positions = np.flatnonzero(benchmark_prices.index >= trade_date)
                        if len(benchmark_positions) and int(benchmark_positions[0]) + horizon < len(benchmark_prices):
                            position = int(benchmark_positions[0]); benchmark_return = float(benchmark_prices.close.iloc[position + horizon] / benchmark_prices.open.iloc[position] - 1)
                            row[f"{label}_{horizon}d"] = row[f"return_{horizon}d"] - benchmark_return
                output.append(row)
        return output

    @staticmethod
    def _max_drawdown(returns: pd.Series) -> float:
        curve = (1 + returns.fillna(0)).cumprod(); return float((curve / curve.cummax() - 1).min()) if len(curve) else 0.0

    def _horizon(self, frame: pd.DataFrame, horizon: int) -> dict[str, Any]:
        target = f"return_{horizon}d"; data = frame.dropna(subset=[target]).copy()
        if len(data) < 3: return {"horizon": horizon, "status": "INSUFFICIENT_EVIDENCE", "sample_count": len(data)}
        ic, p = stats.spearmanr(data.score, data[target]); ic = float(ic) if np.isfinite(ic) else 0.0; p = float(p) if np.isfinite(p) else 1.0
        label_metrics = {}
        for label in (target, f"spy_excess_{horizon}d", f"sector_excess_{horizon}d"):
            subset = data.dropna(subset=[label]) if label in data else data.iloc[:0]
            value, probability = stats.spearmanr(subset.score, subset[label]) if len(subset) >= 3 else (np.nan, np.nan)
            label_metrics[label] = {"sample_count": len(subset), "spearman_ic": round(float(value), 6) if np.isfinite(value) else None, "p_value": round(float(probability), 6) if np.isfinite(probability) else None}
        monthly = data.groupby("month").apply(lambda part: stats.spearmanr(part.score, part[target]).statistic if len(part) >= 3 else np.nan, include_groups=False).dropna()
        icir = float(monthly.mean() / monthly.std(ddof=1)) if len(monthly) >= 2 and monthly.std(ddof=1) else 0.0
        t_value = float(ic * sqrt(max(1, len(data) - 2)) / sqrt(max(1e-12, 1 - ic * ic)))
        split = max(1, int(len(data) * .6)); train, test = data.iloc[:split], data.iloc[split:]
        fold_size = max(1, len(test) // 4); folds = []
        for start in range(split, len(data), fold_size):
            stop = min(len(data), start + fold_size)
            folds.append({"train_end": start, "test_start": start, "test_end": stop, "test_count": stop - start})
        signed = np.sign(test.score) * test[target] - self.cost_bps / 10_000
        sharpe = float(signed.mean() / signed.std(ddof=1) * sqrt(252 / horizon)) if len(signed) >= 2 and signed.std(ddof=1) else 0.0
        train_signed = np.sign(train.score) * train[target] - self.cost_bps / 10_000
        train_sharpe = float(train_signed.mean() / train_signed.std(ddof=1) * sqrt(252 / horizon)) if len(train_signed) >= 2 and train_signed.std(ddof=1) else 0.0
        degradation = 1 - sharpe / train_sharpe if train_sharpe > 0 else None
        symbols, months = Counter(test.symbol), Counter(test.month); denominator = max(1, len(test))
        concentration_ok = (max(symbols.values(), default=0) / denominator <= .5 and max(months.values(), default=0) / denominator <= .5)
        passed = abs(ic) >= .02 and abs(t_value) >= 2 and icir >= .5 and sharpe >= .5 and (degradation is not None and degradation <= .5) and len(test) >= 30 and concentration_ok
        return {"horizon": horizon, "status": "PASSED" if passed else "INSUFFICIENT_EVIDENCE", "sample_count": len(data), "oos_trade_count": len(test),
                "spearman_ic": round(ic, 6), "p_value": round(p, 6), "t_stat": round(t_value, 4), "monthly_ic": [round(float(value), 6) for value in monthly], "icir": round(icir, 4), "label_metrics": label_metrics,
                "walk_forward": {"method": "expanding_window_60pct_initial_train", "train_count": len(train), "test_count": len(test), "folds": folds, "train_sharpe_after_cost": round(train_sharpe, 4), "oos_sharpe_after_cost": round(sharpe, 4), "sharpe_degradation": round(degradation, 4) if degradation is not None else None},
                "strategy": {"cost_bps": self.cost_bps, "hit_rate": round(float((signed > 0).mean()), 4) if len(signed) else None, "max_drawdown": round(self._max_drawdown(pd.Series(signed)), 4), "single_symbol_or_month_dominance": not concentration_ok}}

    def evaluate(self, as_of: str | None = None) -> dict[str, Any]:
        rows = self._rows(as_of)
        sessions = len({snapshot.get("session_date") or str(snapshot.get("captured_at", ""))[:10] for snapshot in self._snapshots(as_of)})
        if not rows:
            return {"status": "INSUFFICIENT_EVIDENCE", "historical_prediction_confidence": None, "horizons": [], "sample_count": 0,
                    "session_count": sessions, "reason": "没有时序对齐的 V3 新闻快照与行情；V2 及更早快照已隔离。", "thresholds": self.thresholds()}
        frame = pd.DataFrame(rows).sort_values(["trade_date", "symbol"])
        results = [self._horizon(frame, horizon) for horizon in self.HORIZONS]
        validated = sessions >= self.MINIMUM_SESSIONS and all(item["status"] == "PASSED" for item in results)
        reason = None if validated else f"需要至少 {self.MINIMUM_SESSIONS} 个合格交易日，且 1、3、5 日样本外指标全部通过。当前为 {sessions} 个交易日。"
        return {"status": "VALIDATED" if validated else "INSUFFICIENT_EVIDENCE", "historical_prediction_confidence": None,
                "sample_count": len(frame), "session_count": sessions, "horizons": results, "reason": reason,
                "thresholds": self.thresholds(), "regime_analysis": {"status": "UNAVAILABLE", "reason": "需要同期 SPY 行情才能分拆市场状态。"}}

    @staticmethod
    def thresholds() -> dict[str, Any]:
        return {"absolute_ic": .02, "absolute_t_stat": 2, "absolute_icir": .5, "oos_sharpe_after_cost": .5,
                "max_sharpe_degradation": .5, "minimum_oos_trades": 30, "minimum_sessions": 60,
                "max_single_symbol_or_month_dominance": .5, "cost_bps": 10}
