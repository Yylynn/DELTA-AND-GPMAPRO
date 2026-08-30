"""Traceable, research-only company-news impact scorecard.

The scorecard deliberately separates observed post-event returns from the
event interpretation.  It never emits an order and it never treats missing
prices or missing news as a neutral market outcome.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.config.news_universe import SECTOR_BENCHMARK
from app.data.providers import CsvDataProvider


HORIZONS = (1, 3, 5)


class NewsImpactScorecardService:
    def __init__(self, news, advice, evaluation, price_root: Path) -> None:
        self.news, self.advice, self.evaluation = news, advice, evaluation
        self.prices = CsvDataProvider(price_root)

    @staticmethod
    def _date(value: str | None) -> pd.Timestamp | None:
        try:
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            return stamp.tz_convert("America/New_York").tz_localize(None).normalize()
        except (TypeError, ValueError):
            return None

    def _frame(self, symbol: str) -> pd.DataFrame | None:
        try:
            frame, _ = self.prices.ohlcv(symbol)
            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
            return frame.sort_values("date").reset_index(drop=True)
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def _start(frame: pd.DataFrame | None, trade_at: str | None) -> int | None:
        day = NewsImpactScorecardService._date(trade_at)
        if frame is None or day is None:
            return None
        positions = np.flatnonzero(frame["date"] >= day)
        return int(positions[0]) if len(positions) else None

    @classmethod
    def _reaction(cls, frame: pd.DataFrame | None, trade_at: str | None) -> dict[str, Any]:
        start = cls._start(frame, trade_at)
        if frame is None or start is None:
            return {"returns": {}, "volume_surprise": {}, "volatility_change": {}}
        baseline = frame.iloc[max(0, start - 20):start]
        baseline_volume = float(baseline.volume.mean()) if len(baseline) else 0.0
        past_returns = baseline.close.pct_change().dropna()
        past_volatility = float(past_returns.std(ddof=0)) if len(past_returns) >= 2 else 0.0
        returns: dict[str, float] = {}
        volume_surprise: dict[str, float] = {}
        volatility_change: dict[str, float] = {}
        for horizon in HORIZONS:
            if start + horizon >= len(frame):
                continue
            key = f"{horizon}d"
            returns[key] = round(float(frame.close.iloc[start + horizon] / frame.open.iloc[start] - 1), 4)
            window = frame.iloc[start:start + horizon + 1]
            if baseline_volume > 0:
                volume_surprise[key] = round(float(window.volume.mean() / baseline_volume - 1), 4)
            window_returns = window.close.pct_change().dropna()
            if len(window_returns) >= 2 and past_volatility > 0:
                volatility_change[key] = round(float(window_returns.std(ddof=0) / past_volatility - 1), 4)
        return {"returns": returns, "volume_surprise": volume_surprise, "volatility_change": volatility_change}

    @staticmethod
    def _impact_label(direction: float) -> str:
        return "BULLISH" if direction >= .15 else "BEARISH" if direction <= -.15 else "UNKNOWN"

    def _event_card(self, event: dict[str, Any], evidence: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any]:
        sector = SECTOR_BENCHMARK.get(symbol, "SPY")
        stock = self._reaction(self._frame(symbol), event.get("earliest_trade_at"))
        market = self._reaction(self._frame("SPY"), event.get("earliest_trade_at"))
        sector_reaction = self._reaction(self._frame(sector), event.get("earliest_trade_at"))
        excess_market = {key: round(value - market["returns"][key], 4) for key, value in stock["returns"].items() if key in market["returns"]}
        excess_sector = {key: round(value - sector_reaction["returns"][key], 4) for key, value in stock["returns"].items() if key in sector_reaction["returns"]}
        related = [evidence[row] for row in event.get("evidence_ids", []) if row in evidence]
        urls = [row.get("url") for row in related if row.get("url")]
        status = "AVAILABLE" if stock["returns"] else "PENDING" if self._start(self._frame(symbol), event.get("earliest_trade_at")) is not None else "UNAVAILABLE"
        source_count = int(event.get("source_count", 0))
        confidence = min(.95, .25 + .15 * source_count + (.25 if event.get("high_impact") else 0) + (.15 if urls else 0))
        return {
            "event_id": event["cluster_id"], "title": event.get("title"), "event_type": event.get("event_type", "OTHER"),
            "direction": self._impact_label(float(event.get("direction", 0))), "direction_score": round(float(event.get("direction", 0)), 4),
            "importance": "HIGH" if event.get("high_impact") else "STANDARD", "impact_horizon": "1–5 个交易日",
            "published_at": event.get("published_at"), "earliest_trade_at": event.get("earliest_trade_at"), "source_count": source_count,
            "confidence": round(confidence, 3), "affected_ticker": symbol, "sector_benchmark": sector,
            "evidence": [{"id": row.get("id"), "title": row.get("title"), "url": row.get("url"), "source": row.get("source_id") or row.get("source"), "published_at": row.get("published_at")} for row in related],
            "reaction": {"status": status, "stock_returns": stock["returns"], "spy_excess_returns": excess_market,
                         "sector_excess_returns": excess_sector, "volume_surprise": stock["volume_surprise"],
                         "volatility_change": stock["volatility_change"],
                         "message": "收益从最早可交易时点的开盘价计算；超额收益仅记录观察结果，不证明因果。" if status == "AVAILABLE" else "等待后续完整交易日。" if status == "PENDING" else "缺少严格时序或本地 OHLCV，未计算市场反应。"},
        }

    def scorecard(self, code: str, *, refresh: bool = False, as_of: str | None = None) -> dict[str, Any]:
        response = self.news.get_at(code, as_of, limit=100) if as_of else self.news.get(code, limit=100, refresh=refresh)
        advice = self.advice.advice(code, as_of=as_of, response=response)
        symbol = str(advice["symbol"]).removeprefix("US.")
        evidence = {str(row.get("id")): row for row in advice.get("evidence", [])}
        events = [self._event_card(event, evidence, symbol) for event in advice.get("events", [])]
        evaluation = self.evaluation.evaluate(as_of=as_of) if as_of else self.evaluation.evaluate()
        reliable = evaluation.get("status") == "VALIDATED"
        return {
            "schema_version": 1, "research_only": True, "generated_at": advice.get("as_of"), "symbol": advice["symbol"],
            "sector_benchmark": SECTOR_BENCHMARK.get(symbol, "SPY"), "data_status": advice.get("status"),
            "impact_score": advice.get("score", 0.0), "sector_spillover_score": None,
            "historical_reliability": {"status": "AVAILABLE" if reliable else "INSUFFICIENT_EVIDENCE", "validated": reliable,
                                       "sample_count": evaluation.get("sample_count", 0), "session_count": evaluation.get("session_count", 0),
                                       "message": "历史校准已通过全部样本外门槛。" if reliable else evaluation.get("reason") or "历史样本不足，评分卡仅供研究观察。",
                                       "horizons": evaluation.get("horizons", [])},
            "market_regime": advice.get("market_regime", {}), "events": events,
            "data_quality": {**advice.get("data_quality", {}), "missing_is_neutral": False,
                             "scorecard_message": "来源或行情缺失会明确标记，绝不解释为中性信号。"},
            "limitations": ["不构成交易建议或因果结论。", "只使用已白名单来源的标题、摘要与本地行情。", "未通过样本外验证前不启用模型校准。"],
        }
