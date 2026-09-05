"""Explainable financial-news classification with a safe local fallback."""
from __future__ import annotations

from math import exp
from typing import Any
import re

from app.services.news_advice import is_generic_sec_filing

ANALYSIS_VERSION = "news-analysis-v3"


POSITIVE = ("beat", "upgrade", "record", "surge", "gain", "raises guidance", "buyback", "contract", "approval")
NEGATIVE = ("miss", "downgrade", "lawsuit", "probe", "antitrust", "recall", "cut guidance", "layoff", "decline")
EVENTS = {
    "EARNINGS": ("earnings", "revenue", "profit", "quarter", "业绩", "营收", "利润", "财报", "季报"),
    "GUIDANCE": ("guidance", "forecast", "outlook", "指引", "预期", "展望"),
    "ANALYST_RATING": ("upgrade", "downgrade", "price target", "上调评级", "下调评级", "目标价"),
    "M&A": ("acquire", "acquisition", "merger", "takeover", "收购", "并购", "合并", "重组"),
    "REGULATION": ("regulation", "probe", "antitrust", "approval", "监管", "调查", "反垄断", "批准"),
    "LEGAL": ("lawsuit", "court", "settlement", "诉讼", "法院", "和解"),
    "PRODUCT": ("launch", "product", "unveils", "发布", "新品", "产品"),
    "OPERATING": ("sales", "demand", "supply chain", "shipment", "store", "subscriber", "销量", "需求", "供应链", "出货", "门店"),
    "MACRO_TRANSMISSION": ("interest rate", "rates", "tariff", "currency", "consumer spending", "利率", "关税", "汇率", "消费支出"),
    "MACRO": ("inflation", "fed", "tariff", "treasury", "recession", "通胀", "美联储", "财政部", "衰退", "央行"),
}


class NewsAnalyzer:
    """Uses FinBERT when the optional local model is installed; never calls a cloud LLM."""

    def __init__(self, *, enable_zh: bool = True):
        self._pipeline: Any | None = None
        self._attempted = False
        self._zh_pipeline: Any | None = None
        self._zh_attempted = False
        self.enable_zh = enable_zh

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

    def _zh_finbert(self):
        """Load the Apache-2.0 Chinese finance classifier locally on demand."""
        if not self.enable_zh or self._zh_attempted:
            return self._zh_pipeline
        self._zh_attempted = True
        try:
            from transformers import pipeline
            self._zh_pipeline = pipeline("text-classification", model="yiyanghkust/finbert-tone-chinese", top_k=None)
        except Exception:
            self._zh_pipeline = None
        return self._zh_pipeline

    @staticmethod
    def _result(*, language: str, method: str, event_type: str, positive: float = 0.0, negative: float = 0.0, neutral: float = 1.0, model_eligible: bool = False) -> dict[str, Any]:
        score = round(positive - negative, 4)
        return {
            "method": method, "analysis_version": ANALYSIS_VERSION, "language": language,
            "positive_probability": round(positive, 4), "negative_probability": round(negative, 4),
            "neutral_probability": round(neutral, 4), "sentiment_score": score,
            "direction": "BULLISH" if score >= .15 else "BEARISH" if score <= -.15 else "NEUTRAL",
            "event_type": event_type,
            "high_impact": event_type in {"EARNINGS", "GUIDANCE", "REGULATION", "LEGAL"} and abs(score) >= .35,
            "model_eligible": model_eligible,
        }

    @staticmethod
    def _zh_labels(values: list[dict[str, Any]]) -> tuple[float, float, float]:
        # The model card defines LABEL_0/1/2 as neutral/positive/negative.
        labels = {str(item.get("label", "")).casefold(): float(item.get("score", 0)) for item in values}
        return labels.get("label_1", labels.get("positive", 0.0)), labels.get("label_2", labels.get("negative", 0.0)), labels.get("label_0", labels.get("neutral", 0.0))

    def analyze(self, title: str, summary: str | None = None, event_type_hint: str | None = None) -> dict[str, Any]:
        text = f"{title} {summary or ''}".strip()
        language = "ZH" if re.search(r"[\u3400-\u9fff]", text) else "EN"
        event_type = event_type_hint or next((name for name, terms in EVENTS.items() if any(term in text.casefold() for term in terms)), "OTHER")
        if is_generic_sec_filing(title):
            return self._result(language=language, method="METADATA_ONLY", event_type=event_type)
        if language == "ZH":
            model = self._zh_finbert()
            if not model:
                # Keep topic classification auditable when optional model weights
                # are absent; never fabricate a lexical sentiment score for Chinese.
                return self._result(language=language, method="ZH_TOPIC_ONLY", event_type=event_type)
            positive, negative, neutral = self._zh_labels(model(text[:512])[0])
            # Chinese news is research/radar-only until separately calibrated.
            return self._result(language=language, method="ZH_FINBERT", event_type=event_type, positive=positive, negative=negative, neutral=neutral)
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
        return self._result(language=language, method=status, event_type=event_type, positive=positive, negative=negative, neutral=neutral, model_eligible=status == "FINBERT")


def freshness_weight(hours: float) -> float:
    return round(max(.15, exp(-max(0, hours) / 36)), 4)
