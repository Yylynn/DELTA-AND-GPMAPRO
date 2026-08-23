"""Explainable, read-only company and US-market research summaries."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _dated_bounds(items: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    dates = sorted(item["published_at"] for item in items if item.get("published_at"))
    return (dates[0], dates[-1]) if dates else (None, None)


def _direction(items: list[dict[str, Any]]) -> tuple[str, float]:
    scores = [float(item.get("analysis", {}).get("sentiment_score", 0)) for item in items]
    score = sum(scores) / len(scores) if scores else 0.0
    return ("POSITIVE" if score >= .15 else "NEGATIVE" if score <= -.15 else "NEUTRAL", round(score, 4))


class NewsResearchService:
    """Turns persisted article metadata into citations-first research cards."""

    def __init__(self, news, alerts) -> None:
        self.news, self.alerts = news, alerts

    def company_card(self, response: dict[str, Any]) -> dict[str, Any]:
        articles = list(response.get("company_items", []))
        status = response.get("source_status")
        if status in {"COMPANY_UNAVAILABLE", "UNAVAILABLE"}:
            coverage, reason = "SOURCE_UNAVAILABLE", response.get("warning") or "公司新闻源暂不可用。"
        elif not articles:
            coverage, reason = "COVERAGE_GAP", "当前已配置公司新闻源未返回可验证的公司新闻；这不代表公司情况中性、利好或利空。"
        else:
            coverage, reason = "AVAILABLE", None
        direction, score = _direction(articles)
        sources = sorted({item.get("source") for item in articles if item.get("source")})
        first, latest = _dated_bounds(articles)
        events = Counter(item.get("analysis", {}).get("event_type", "OTHER") for item in articles)
        risks = [item for item in articles if item.get("analysis", {}).get("high_impact") and item.get("analysis", {}).get("direction") == "BEARISH"]
        catalysts = [item for item in articles if item.get("analysis", {}).get("high_impact") and item.get("analysis", {}).get("direction") == "BULLISH"]
        confidence = min(.90, .25 + .15 * len(articles) + .10 * max(0, len(sources) - 1)) if articles else 0.0
        timeline = [{
            "id": item["id"], "title": item["title"], "source": item.get("source"), "published_at": item.get("published_at"),
            "url": item.get("url"), "event_type": item.get("analysis", {}).get("event_type", "OTHER"),
            "direction": item.get("analysis", {}).get("direction", "NEUTRAL"), "method": item.get("analysis", {}).get("method", "UNKNOWN"),
        } for item in articles]
        return {
            "symbol": response["symbol"], "generated_at": datetime.now(timezone.utc).isoformat(), "coverage_status": coverage,
            "coverage_reason": reason, "assessment": "INSUFFICIENT" if coverage != "AVAILABLE" else direction,
            "sentiment_score": score if coverage == "AVAILABLE" else None, "confidence": round(confidence, 4), "coverage_score": round(confidence, 4),
            "historical_prediction_confidence": None, "validation_status": "NOT_VALIDATED",
            "facts": timeline, "event_timeline": timeline, "positive_catalysts": [item["id"] for item in catalysts],
            "risk_items": [item["id"] for item in risks],
            "supported_interpretation": "仅根据已列出的新闻标题、时间和来源归纳；不推断未披露的经营或财务事实。" if articles else None,
            "unknowns": ["公司新闻源仍可能存在覆盖缺口。", "未抓取文章正文；不能据此确认完整经营影响。"] if coverage != "AVAILABLE" else ["仅保留标题级证，需阅读原文链接核实细节。"],
            "data_quality": {"article_count": len(articles), "source_count": len(sources), "sources": sources, "earliest_published_at": first, "latest_published_at": latest, "entity_match_count": sum(bool(item.get("entity_matches")) for item in articles), "source_status": status, "fetched_at": response.get("fetched_at")},
        }

    def market_regime(self, response: dict[str, Any]) -> dict[str, Any]:
        articles = list(response.get("market_items", []))
        direction, score = _direction(articles)
        sources = sorted({item.get("source_id") for item in articles if item.get("source_id")})
        themes = Counter(item.get("analysis", {}).get("event_type", "OTHER") for item in articles)
        alert_snapshot = self.alerts.snapshot()
        active = alert_snapshot.get("active_alerts", [])
        volatility_risk = any(item.get("severity") == "RISK" for item in active)
        volatility_watch = volatility_risk or any(item.get("severity") == "WATCH" for item in active)
        if volatility_risk or (score <= -.15 and len(sources) >= 2): regime = "RISK_OFF"
        elif volatility_watch or score <= -.05: regime = "CAUTION"
        elif score >= .15 and len(sources) >= 2: regime = "RISK_ON"
        else: regime = "NEUTRAL"
        first, latest = _dated_bounds(articles)
        validation_available = bool(alert_snapshot.get("last_check"))
        confidence = min(.85, .20 + .12 * len(sources) + .03 * min(len(articles), 10) + (.12 if validation_available else 0))
        return {
            "market": "US", "generated_at": datetime.now(timezone.utc).isoformat(), "regime": regime,
            "news_direction": direction, "news_score": score, "confidence": round(confidence, 4), "coverage_score": round(confidence, 4),
            "historical_prediction_confidence": None, "validation_status": "NOT_VALIDATED",
            "cross_source_confirmation": len(sources), "themes": [{"event_type": key, "article_count": value} for key, value in themes.most_common()],
            "evidence": [{key: item.get(key) for key in ("id", "title", "source", "published_at", "url", "analysis")} for item in articles[:20]],
            "data_quality": {"article_count": len(articles), "source_count": len(sources), "earliest_published_at": first, "latest_published_at": latest, "fetched_at": response.get("fetched_at")},
            "volatility_validation": {"status": "AVAILABLE" if validation_available else "UNAVAILABLE", "active_alert_count": len(active), "has_risk_alert": volatility_risk, "last_check": alert_snapshot.get("last_check")},
            "uncertainty": "市场新闻或波动率验证不完整时，状态仅为风险背景，不是市场涨跌预测。" if not validation_available or not articles else "新闻与波动率仅用于风险背景，不构成交易指令。",
        }

    @staticmethod
    def persist(root: Path, payload: dict[str, Any]) -> Path:
        """Save the rendered conclusion with its citations for point-in-time replay."""
        generated_at = payload["company"]["generated_at"]
        symbol = payload["company"]["symbol"].replace(".", "_")
        folder = root / "news_research_history" / symbol
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{generated_at.replace(':', '-').replace('+', '_')}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
