"""Explainable financial-news classification with a safe local fallback."""
from __future__ import annotations

from math import exp
from typing import Any


POSITIVE = ("beat", "upgrade", "record", "surge", "gain", "raises guidance", "buyback", "contract", "approval")
NEGATIVE = ("miss", "downgrade", "lawsuit", "probe", "antitrust", "recall", "cut guidance", "layoff", "decline")
EVENTS = {
    "EARNINGS": ("earnings", "revenue", "profit", "quarter"),
    "GUIDANCE": ("guidance", "forecast", "outlook"),
    "ANALYST_RATING": ("upgrade", "downgrade", "price target"),
    "M&A": ("acquire", "acquisition", "merger", "takeover"),
    "REGULATION": ("regulation", "probe", "antitrust", "approval"),
    "LEGAL": ("lawsuit", "court", "settlement"),
    "PRODUCT": ("launch", "product", "unveils"),
    "MACRO": ("inflation", "fed", "tariff", "treasury", "recession"),
}


class NewsAnalyzer:
    """Uses FinBERT when the optional local model is installed; never calls a cloud LLM."""

    def __init__(self):
        self._pipeline: Any | None = None
        self._attempted = False

    def _finbert(self):
        if self._attempted:
            return self._pipeline
        self._attempted = True
        try:
            from transformers import pipeline
            self._pipeline = pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
        except Exception:
            self._pipeline = None
        return self._pipeline

    def analyze(self, title: str, summary: str | None = None) -> dict[str, Any]:
        text = f"{title} {summary or ''}".strip()
        event_type = next((name for name, terms in EVENTS.items() if any(term in text.casefold() for term in terms)), "OTHER")
        model = self._finbert()
        if model:
            labels = {item["label"].casefold(): float(item["score"]) for item in model(text[:512])[0]}
            positive, negative, neutral = labels.get("positive", 0.0), labels.get("negative", 0.0), labels.get("neutral", 0.0)
            status = "FINBERT"
        else:
            lower = text.casefold(); pos = sum(term in lower for term in POSITIVE); neg = sum(term in lower for term in NEGATIVE)
            positive, negative = (0.70, 0.10) if pos > neg else (0.10, 0.70) if neg > pos else (0.15, 0.15)
            neutral = 1 - positive - negative
            status = "RULE_FALLBACK"
        score = round(positive - negative, 4)
        return {
            "method": status,
            "positive_probability": round(positive, 4), "negative_probability": round(negative, 4),
            "neutral_probability": round(neutral, 4), "sentiment_score": score,
            "direction": "BULLISH" if score >= .15 else "BEARISH" if score <= -.15 else "NEUTRAL",
            "event_type": event_type,
            "high_impact": event_type in {"EARNINGS", "GUIDANCE", "REGULATION", "LEGAL"} and abs(score) >= .35,
        }


def freshness_weight(hours: float) -> float:
    return round(max(.15, exp(-max(0, hours) / 36)), 4)
