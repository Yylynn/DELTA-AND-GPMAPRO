"""Compose existing research engines into a point-in-time evidence snapshot.

This module deliberately produces evidence only.  It contains no trade action,
entry, target, or position-sizing vocabulary.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import pandas as pd

from app.config.evidence_config import EVIDENCE_CONFIG, EvidenceConfig
from app.models.evidence import EvidenceItem
from app.quant.delta_time import ITDDeltaEngine, ManualDeltaEngine
from app.services.data_freshness import freshness_snapshot
from app.services.event_backtest import EventBacktestService
from app.services.gpmapro_engine import GpmaProEngine
from app.services.volume_monitor import VolumeMonitor
from app.services.news import NewsService


class EvidenceEngine:
    def __init__(self, config: EvidenceConfig = EVIDENCE_CONFIG):
        self.config = config
        self.gpma, self.volume, self.backtest = GpmaProEngine(), VolumeMonitor(), EventBacktestService()
        self.news = NewsService(Path(__file__).resolve().parents[3] / "data" / "news_cache")

    def _item(self, *, id: str, source: str, category: str, label: str, direction: str, strength: float, confidence: float, status: str, as_of: str, details: dict | None = None) -> EvidenceItem:
        return EvidenceItem(id=id, source=source, category=category, label=label, direction=direction, strength=round(max(0, min(1, strength)), 4), confidence=round(max(0, min(1, confidence)), 4), weight=self.config.weights[source], status=status, as_of=as_of, details=details or {})

    @staticmethod
    def _manual_events() -> list[dict]:
        store = Path(__file__).resolve().parents[3] / "data" / "delta_events.json"
        return json.loads(store.read_text(encoding="utf-8")) if store.exists() else []

    def _delta(self, bars: pd.DataFrame, as_of: date, symbol: str) -> list[EvidenceItem]:
        results = []
        manual = ManualDeltaEngine([item for item in self._manual_events() if item.get("enabled", True) and item.get("symbol", "*").upper() in {"*", symbol.upper()}]).windows()
        # The skill model is the default DELTA source.  Manual records remain
        # a separately auditable overlay, not an algorithm replacement.
        generated = [type("Window", (), item) for item in ITDDeltaEngine().signal_windows(bars)]
        for window in [*generated, *manual]:
            published_at = date.fromisoformat(str(window.metadata.get("published_at") or window.anchor_date))
            if published_at < as_of and window.window_start <= as_of <= window.window_end:
                event_type = window.event_type.value if hasattr(window.event_type, "value") else str(window.event_type)
                direction = "BULLISH" if event_type == "LOW" else "BEARISH"
                results.append(self._item(id=f"delta_{window.event_id}", source="DELTA", category="TIME", label=f"DELTA {event_type.lower()} window active", direction=direction, strength=.8, confidence=window.confidence, status="ACTIVE", as_of=as_of.isoformat(), details={"event_type": event_type, "published_at": published_at.isoformat(), "window_start": window.window_start.isoformat(), "window_end": window.window_end.isoformat(), "source": window.source}))
        return results

    def _gpmapro(self, bars: pd.DataFrame, as_of: str) -> list[EvidenceItem]:
        data = self.gpma.calculate(bars, as_of); row = data.iloc[-1]; output = []
        trend = "BULLISH" if row.bull_bg else "BEARISH" if row.bear_bg else "NEUTRAL"
        output.append(self._item(id="gpmapro_trend", source="GPMAPRO", category="TREND", label="GPMAPRO EMA trend structure", direction=trend, strength=.9 if row.bull_strong else .7 if trend != "NEUTRAL" else .2, confidence=.85, status="AVAILABLE", as_of=as_of, details={"bull_bg": bool(row.bull_bg), "bull_strong": bool(row.bull_strong), "bear_bg": bool(row.bear_bg)}))
        improving = row.macd >= 0 and row.macd >= data.macd.iloc[-2] if len(data) > 1 else row.macd >= 0
        deteriorating = row.macd < 0 and (len(data) == 1 or row.macd <= data.macd.iloc[-2])
        momentum = "BULLISH" if improving else "BEARISH" if deteriorating else "NEUTRAL"
        output.append(self._item(id="gpmapro_macd", source="GPMAPRO", category="MOMENTUM", label="GPMAPRO MACD momentum", direction=momentum, strength=min(.9, .3 + abs(float(row.macd)) / max(abs(float(row.close)), 1) * 40), confidence=.75, status="AVAILABLE", as_of=as_of, details={"macd": float(row.macd), "previous_macd": None if len(data) == 1 else float(data.macd.iloc[-2])}))
        for name, direction in (("b1", "BULLISH"), ("b2", "BULLISH"), ("b3", "BULLISH"), ("s1", "BEARISH"), ("s2", "BEARISH")):
            hits = data.index[data[name]].tolist()
            if not hits: continue
            bars_since = len(data) - 1 - hits[-1]
            status = "ACTIVE" if bars_since <= self.config.active_signal_bars else "RECENT" if bars_since <= self.config.recent_signal_bars else "EXPIRED"
            output.append(self._item(id=f"gpmapro_{name}", source="GPMAPRO", category="SIGNAL", label=f"{name.upper()} signal {status.lower()}", direction=direction, strength=.78, confidence=.8 if status == "ACTIVE" else .55 if status == "RECENT" else .15, status=status, as_of=as_of, details={"bars_since_signal": bars_since}))
        return output

    def _volume(self, bars: pd.DataFrame, symbol: str, timeframe: str, as_of: str) -> tuple[list[EvidenceItem], dict]:
        snapshot = self.volume.snapshot(bars, symbol, timeframe, as_of)
        context = snapshot["price_volume_context"]
        mapping = {"UP_ON_HIGH_VOLUME": ("BULLISH", .75), "DOWN_ON_HIGH_VOLUME": ("BEARISH", .75), "UP_ON_LOW_VOLUME": ("NEUTRAL", .3), "DOWN_ON_LOW_VOLUME": ("NEUTRAL", .3)}
        direction, strength = mapping.get(context, ("NEUTRAL", .15))
        item = self._item(id="volume_price_context", source="VOLUME", category="PRICE_VOLUME", label=context.replace("_", " ").title(), direction=direction, strength=strength, confidence=.75, status="AVAILABLE", as_of=as_of, details={"relative_volume": snapshot["relative_volume"], "volume_level": snapshot["volume_level"], "price_change_pct": snapshot["price_change_pct"]})
        return [item], snapshot["data"]

    @staticmethod
    def _sample_confidence(count: int) -> float:
        return .20 if count < 5 else .40 if count < 10 else .65 if count < 30 else .85

    def _historical(self, bars: pd.DataFrame, as_of: str, event_type: str | None) -> list[EvidenceItem]:
        if not event_type: return []
        # The backtest sees only bars available by as_of; incomplete forward returns are excluded by the existing service.
        known = bars.copy(); known["date"] = pd.to_datetime(known.date); known = known[known.date <= pd.Timestamp(as_of)].copy()
        outcome = self.backtest.run(known, start_date=None, end_date=as_of)
        stats = outcome.get("groups", {}).get(event_type, {}).get("10", {})
        count = int((stats or {}).get("sample_count", 0))
        if not stats or count == 0: return []
        median, average = stats["median_return"], stats["average_return"]
        direction = "BULLISH" if median > 0 else "BEARISH" if median < 0 else "NEUTRAL"
        strength = min(.95, abs(float(median)) / 10) if median is not None else 0
        return [self._item(id=f"backtest_{event_type.lower()}_10d", source="BACKTEST", category="HISTORICAL", label=f"Historical DELTA {event_type.lower()} 10D outcomes", direction=direction, strength=strength, confidence=self._sample_confidence(count), status="AVAILABLE", as_of=as_of, details={"event_type": event_type, "horizon_days": 10, "sample_count": count, "median_return": median, "average_return": average, "mfe": stats["mfe"], "mae": stats["mae"], "knowledge_mode": "POINT_IN_TIME"})]

    def _news(self, symbol: str, as_of: str | None, resolved: str) -> tuple[list[EvidenceItem], dict]:
        code = symbol.upper() if symbol.upper().startswith(("US.", "HK.")) else f"US.{symbol.upper()}"
        trace = self.news.insight(code, as_of=as_of)
        if trace.get("status") != "AVAILABLE":
            return [], trace
        company = trace.get("company", {})
        if company.get("status") != "AVAILABLE":
            return [], trace
        direction = company["direction"]
        output = [self._item(id="news_company_sentiment", source="NEWS", category="NEWS_SENTIMENT", label="公司新闻情绪（可追溯来源）", direction=direction, strength=abs(float(company["score"])), confidence=float(company["confidence"]), status="AVAILABLE", as_of=resolved, details={"company": company, "citations": trace["citations"]})]
        if trace["high_risk"]:
            output.append(self._item(id="news_high_risk_catalyst", source="NEWS", category="CATALYST", label="高影响负面新闻催化剂", direction="BEARISH", strength=.9, confidence=float(company["confidence"]), status="ACTIVE", as_of=resolved, details={"citations": trace["high_risk"]}))
        return output, trace

    def snapshot(self, bars: pd.DataFrame, symbol: str, timeframe: str, as_of: str | None = None) -> dict:
        dates = pd.to_datetime(bars.date); available = dates[dates <= pd.Timestamp(as_of)] if as_of else dates
        if available.empty: raise ValueError("No OHLCV data is available at as_of")
        resolved = available.max().date(); resolved_text = resolved.isoformat()
        delta = self._delta(bars[dates <= pd.Timestamp(resolved_text)].copy(), resolved, symbol)
        evidence = delta + self._gpmapro(bars, resolved_text)
        volume, data = self._volume(bars, symbol, timeframe, resolved_text); evidence += volume
        current_type = delta[0].details["event_type"] if delta else None
        evidence += self._historical(bars, resolved_text, current_type)
        news_evidence, news_trace = self._news(symbol, as_of, resolved_text); evidence += news_evidence
        # Freshness is assessed at the requested point in time, or at the real
        # current date for a live snapshot.  Indicator calculations remain cut
        # off at the latest available bar.
        freshness_reference = pd.Timestamp(as_of).date() if as_of else date.today()
        freshness = freshness_snapshot(resolved, len(available), freshness_reference)["freshness"]
        data = {**data, "freshness": freshness}
        penalty = {"STALE": self.config.stale_confidence_multiplier, "VERY_STALE": self.config.very_stale_confidence_multiplier, "UNKNOWN": self.config.unknown_confidence_multiplier}.get(freshness, 1.0)
        evidence.append(self._item(id="data_freshness", source="DATA", category="DATA_QUALITY", label=f"Data freshness: {freshness}", direction="NEUTRAL" if freshness != "UNKNOWN" else "UNKNOWN", strength=1, confidence=penalty, status="AVAILABLE", as_of=resolved_text, details={**data, "freshness": freshness, "confidence_multiplier": penalty}))
        scored = [item for item in evidence if item.status != "EXPIRED" and item.direction in {"BULLISH", "BEARISH"}]
        bull = sum(item.strength * item.confidence * item.weight for item in scored if item.direction == "BULLISH") * penalty
        bear = sum(item.strength * item.confidence * item.weight for item in scored if item.direction == "BEARISH") * penalty
        neutral = sum(item.strength * item.confidence * item.weight for item in evidence if item.direction in {"NEUTRAL", "UNKNOWN"})
        total = bull + bear + neutral
        scores = {"bullish": round(bull / total, 4) if total else 0, "bearish": round(bear / total, 4) if total else 0, "neutral": round(neutral / total, 4) if total else 1}
        strong_both = scores["bullish"] >= self.config.mixed_min_score and scores["bearish"] >= self.config.mixed_min_score
        if bull + bear < self.config.minimum_score: balance = "INSUFFICIENT"
        elif strong_both: balance = "MIXED"
        elif abs(scores["bullish"] - scores["bearish"]) <= self.config.dominance_margin: balance = "BALANCED"
        else: balance = "BULLISH" if scores["bullish"] > scores["bearish"] else "BEARISH"
        conflicts = []
        groups = {"DELTA": [x for x in scored if x.source == "DELTA"], "GPMAPRO_TREND": [x for x in scored if x.id == "gpmapro_trend"], "GPMAPRO_SIGNAL": [x for x in scored if x.category == "SIGNAL"], "VOLUME": [x for x in scored if x.source == "VOLUME"], "BACKTEST": [x for x in scored if x.source == "BACKTEST"], "NEWS": [x for x in scored if x.source == "NEWS"]}
        for left, right in (("DELTA", "GPMAPRO_TREND"), ("GPMAPRO_TREND", "GPMAPRO_SIGNAL"), ("GPMAPRO_SIGNAL", "VOLUME"), ("DELTA", "BACKTEST")):
            if groups[left] and groups[right] and {x.direction for x in groups[left]} != {x.direction for x in groups[right]}:
                if any(a.direction != b.direction for a in groups[left] for b in groups[right]): conflicts.append({"left": left, "right": right, "type": "DIRECTION_CONFLICT"})
        summary = [f"{item.label}: {item.direction.lower()} evidence." for item in evidence if item.status != "EXPIRED"]
        return {"symbol": symbol.upper(), "timeframe": timeframe, "as_of": resolved_text, "evidence_balance": balance, "scores": scores, "confidence": round(min(1, (sum(x.confidence for x in scored) / len(scored) if scored else 0) * penalty), 4), "evidence": [x.model_dump() for x in evidence], "conflicts": conflicts, "data_quality": {"freshness": freshness, "latest_bar_date": resolved_text}, "news_trace": news_trace, "summary": summary}
