"""Strict, explainable News Factor V3 advice and low-weight decision overlay."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import tanh
import json
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd


FACTOR_VERSION = "NEWS_FACTOR_V3"
EVENT_WEIGHT = {
    "EARNINGS": 1.0,
    "GUIDANCE": 1.0,
    "M&A": .9,
    "REGULATION": .9,
    "LEGAL": .9,
    "OPERATING": .7,
    "PRODUCT": .65,
    "ANALYST_RATING": .6,
    "OTHER": .35,
}
SOURCE_QUALITY = {"sec_edgar": 1.0, "finnhub_company": .9, "openbb_yfinance": .85}
ACTION_LABEL = {"BUY": "买入", "ACCUMULATE": "适当买入", "HOLD": "观望", "REDUCE": "适当卖出", "SELL": "卖出"}
ACTION_GUIDANCE = {
    "BUY": "新闻因子支持已有多头结论，但不代表自动下单。",
    "ACCUMULATE": "新闻因子仅支持小幅多头暴露，仍需技术条件确认。",
    "HOLD": "不根据新闻单独新增仓位，继续观察可验证证据。",
    "REDUCE": "已有多头考虑减仓，新闻只作为风险覆盖层。",
    "SELL": "已有多头以清仓为优先，不建立空头。",
}
_GENERIC_SEC = re.compile(r"^[A-Z0-9._-]+\s+(?:8-K|10-Q|10-K|4)(?:/A)?\s+SEC\s+filing$", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {"the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "at", "with", "from", "says", "said"}


def is_generic_sec_filing(title: str) -> bool:
    """Return true when a filing title carries metadata but no directional fact."""
    return bool(_GENERIC_SEC.fullmatch(title.strip()))


def _timestamp(value: Any, fallback: datetime | None = None) -> pd.Timestamp:
    stamp = pd.Timestamp(value if value is not None else fallback or datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _decay(hours: float, half_life: float) -> float:
    return float(2 ** (-max(0.0, hours) / half_life))


def _tokens(title: str, symbol: str) -> set[str]:
    ignored = {*_STOP_WORDS, symbol.casefold(), "sec", "filing"}
    return {value for value in _TOKEN.findall(title.casefold()) if value not in ignored and len(value) > 1}


def _same_event(left: dict[str, Any], right: dict[str, Any], symbol: str) -> bool:
    if left["event_type"] != right["event_type"]:
        return False
    if abs(left["published"].timestamp() - right["published"].timestamp()) > 36 * 3600:
        return False
    left_tokens, right_tokens = _tokens(left["item"]["title"], symbol), _tokens(right["item"]["title"], symbol)
    if not left_tokens or not right_tokens:
        return left["item"]["title"].strip().casefold() == right["item"]["title"].strip().casefold()
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= .72


def _weighted_mean(rows: Iterable[dict[str, Any]], field: str) -> float:
    values = list(rows)
    if not values:
        return 0.0
    # `field` already contains event weight, relevance, source quality and
    # time decay. Dividing by its sum would cancel decay for a single event.
    return float(np.clip(sum(float(item["direction"]) * float(item[field]) for item in values) / len(values), -1, 1))


class NewsFactorCalculator:
    """Pure V3 factor calculation. It performs no network or price-data access."""

    def calculate(
        self,
        response: dict[str, Any],
        captured_at: str | datetime,
        *,
        history_counts: Iterable[float] = (),
    ) -> dict[str, Any]:
        now = _timestamp(captured_at)
        symbol = str(response.get("symbol") or "").upper().removeprefix("US.")
        company_items = list(response.get("company_items", response.get("items", [])))
        prepared: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        timestamped = 0
        model_ready = 0

        for item in company_items:
            analysis = item.get("analysis", {})
            published_at = item.get("published_at")
            has_time = bool(published_at and item.get("earliest_trade_at"))
            timestamped += int(has_time)
            generic_sec = is_generic_sec_filing(str(item.get("title") or ""))
            eligible = bool(
                item.get("scope", "COMPANY") == "COMPANY"
                and item.get("entity_status") == "ACCEPTED"
                and has_time
                and item.get("factor_eligible")
                and analysis.get("method") == "FINBERT"
                and analysis.get("model_eligible", True)
                and not generic_sec
            )
            exclusion = None
            if generic_sec:
                exclusion = "通用 SEC 申报标题不包含方向性事实"
            elif not has_time:
                exclusion = "缺少严格时序字段"
            elif analysis.get("method") != "FINBERT" or not analysis.get("model_eligible", True):
                exclusion = "非 FinBERT 输出不参与交易方向"
            elif item.get("entity_status") != "ACCEPTED":
                exclusion = "公司实体未通过匹配"
            elif not item.get("factor_eligible"):
                exclusion = "未通过因子资格检查"

            evidence_row = {
                key: item.get(key)
                for key in ("id", "title", "url", "source", "source_id", "publisher", "published_at", "available_at", "earliest_trade_at", "summary")
            }
            evidence_row.update(
                eligible=eligible,
                exclusion_reason=exclusion,
                direction=analysis.get("direction", "NEUTRAL") if eligible else "NEUTRAL",
                event_type=analysis.get("event_type", "OTHER"),
                method=analysis.get("method", "UNKNOWN"),
                high_impact=bool(analysis.get("high_impact")) if eligible else False,
                contribution=0.0,
            )
            evidence.append(evidence_row)
            if not eligible:
                continue
            model_ready += 1
            published = _timestamp(published_at)
            if published > now:
                evidence_row["exclusion_reason"] = "发布时间晚于评估时间"
                evidence_row["eligible"] = False
                model_ready -= 1
                continue
            hours = max(0.0, (now - published).total_seconds() / 3600)
            if hours > 24 * 7:
                evidence_row["exclusion_reason"] = "超过七日新闻窗口"
                evidence_row["eligible"] = False
                model_ready -= 1
                continue
            entity_matches = {str(value).casefold() for value in item.get("entity_matches", [])}
            entity_tickers = {str(value).upper() for value in item.get("entity_tickers", [])}
            relevance = 1.0 if symbol.casefold() in entity_matches or symbol in entity_tickers else .8
            source_quality = SOURCE_QUALITY.get(str(item.get("source_id") or ""), .75)
            event_type = str(analysis.get("event_type") or "OTHER")
            direction = float(analysis.get("positive_probability", 0)) - float(analysis.get("negative_probability", 0))
            if not direction and analysis.get("sentiment_score") is not None:
                direction = float(analysis.get("sentiment_score", 0))
            prepared.append({
                "item": item,
                "evidence": evidence_row,
                "published": published,
                "hours": hours,
                "event_type": event_type,
                "direction": float(np.clip(direction, -1, 1)),
                "event_weight": EVENT_WEIGHT.get(event_type, .35),
                "relevance": relevance,
                "source_quality": source_quality,
            })

        clusters: list[list[dict[str, Any]]] = []
        for row in sorted(prepared, key=lambda value: value["published"], reverse=True):
            cluster = next((group for group in clusters if _same_event(group[0], row, symbol)), None)
            if cluster is None:
                clusters.append([row])
            else:
                cluster.append(row)

        cluster_rows: list[dict[str, Any]] = []
        for index, members in enumerate(clusters):
            representative = max(members, key=lambda value: (value["source_quality"], value["published"]))
            quality_total = sum(float(value["source_quality"]) for value in members)
            direction = sum(float(value["direction"]) * float(value["source_quality"]) for value in members) / quality_total if quality_total else 0.0
            hours = min(float(value["hours"]) for value in members)
            source_ids = sorted({str(value["item"].get("source_id") or value["item"].get("source") or "unknown") for value in members})
            base_weight = representative["event_weight"] * representative["relevance"] * representative["source_quality"]
            short_weight = base_weight * _decay(hours, 18)
            weekly_weight = base_weight * _decay(hours, 72)
            signed_weekly = direction * weekly_weight
            high_impact = any(bool(value["item"].get("analysis", {}).get("high_impact")) for value in members)
            cluster_id = f"{symbol}:{index}:{representative['item'].get('id') or 'event'}"
            cluster_row = {
                "cluster_id": cluster_id,
                "title": representative["item"].get("title"),
                "event_type": representative["event_type"],
                "direction": round(direction, 6),
                "high_impact": high_impact,
                "source_count": len(source_ids),
                "sources": source_ids,
                "published_at": representative["item"].get("published_at"),
                "earliest_trade_at": min((value["item"].get("earliest_trade_at") for value in members if value["item"].get("earliest_trade_at")), default=None),
                "short_weight": short_weight,
                "weekly_weight": weekly_weight,
                "contribution": round(signed_weekly, 6),
                "evidence_ids": [value["item"].get("id") for value in members],
            }
            cluster_rows.append(cluster_row)
            for member in members:
                member["evidence"]["cluster_id"] = cluster_id
                member["evidence"]["contribution"] = round(signed_weekly, 6)

        short_rows = [row for row in cluster_rows if (_timestamp(row["published_at"]) - now).total_seconds() >= -24 * 3600]
        short_sentiment = _weighted_mean(short_rows, "short_weight")
        weekly_sentiment = _weighted_mean(cluster_rows, "weekly_weight")
        event_impact = max((row["contribution"] for row in cluster_rows if row["high_impact"]), key=abs, default=0.0)
        positive_count = sum(float(row["direction"]) >= .15 for row in cluster_rows)
        negative_count = sum(float(row["direction"]) <= -.15 for row in cluster_rows)
        breadth = (positive_count - negative_count) / len(cluster_rows) if cluster_rows else 0.0
        historical = np.asarray([float(value) for value in history_counts], dtype=float)
        attention = 0.0
        if len(historical) >= 20 and float(historical.std(ddof=0)) > 0:
            z_value = (len(cluster_rows) - float(historical.mean())) / float(historical.std(ddof=0))
            dominant = np.sign(short_sentiment + weekly_sentiment)
            attention = tanh(float(z_value) / 2) * float(dominant)
        negative_tail = max((abs(float(row["contribution"])) for row in cluster_rows if row["high_impact"] and float(row["direction"]) < 0), default=0.0)
        factor_score = float(np.clip(
            .40 * short_sentiment + .25 * weekly_sentiment + .15 * event_impact + .10 * breadth + .10 * attention - .25 * negative_tail,
            -1,
            1,
        ))

        sources = {source for row in cluster_rows for source in row["sources"]}
        timestamp_completeness = timestamped / max(1, len(company_items))
        model_eligibility = model_ready / max(1, timestamped)
        freshness = float(np.mean([_decay(float(row["hours"]), 72) for row in prepared])) if prepared else 0.0
        confidence = 0.0
        if cluster_rows:
            confidence = (
                .30 * min(1.0, len(cluster_rows) / 4)
                + .25 * min(1.0, len(sources) / 2)
                + .20 * model_eligibility
                + .15 * timestamp_completeness
                + .10 * freshness
            )
            has_permitted_summary = any(bool(row["item"].get("summary") and row["item"].get("allow_summary")) for row in prepared)
            confidence = min(.95 if has_permitted_summary else .85, confidence)

        bias = "BULLISH" if factor_score >= .15 else "BEARISH" if factor_score <= -.15 else "NEUTRAL"
        # The aggregate advice includes every retained event, so it is not
        # tradable until the newest event has itself reached a valid open.
        earliest = max((row["earliest_trade_at"] for row in cluster_rows if row["earliest_trade_at"]), key=_timestamp, default=None)
        components = {
            "short_term_sentiment": round(short_sentiment, 6),
            "weekly_sentiment": round(weekly_sentiment, 6),
            "major_event_impact": round(float(event_impact), 6),
            "directional_breadth": round(float(breadth), 6),
            "attention_surprise": round(float(attention), 6),
            "negative_tail_risk": round(float(negative_tail), 6),
        }
        return {
            "factor_version": FACTOR_VERSION,
            "factor_score": round(factor_score, 6),
            "baseline_score": round(factor_score, 6),
            "bias": bias,
            "confidence": round(confidence, 6),
            "components": components,
            "events": sorted(cluster_rows, key=lambda row: abs(float(row["contribution"])), reverse=True),
            "evidence": evidence,
            "news_count": len(cluster_rows),
            "earliest_trade_at": earliest,
            "negative_major_event": bool(negative_tail),
            "data_quality": {
                "article_count": len(company_items),
                "valid_article_count": model_ready,
                "unique_event_count": len(cluster_rows),
                "duplicate_count": max(0, model_ready - len(cluster_rows)),
                "source_count": len(sources),
                "sources": sorted(sources),
                "published_at_completeness": round(timestamp_completeness, 4),
                "model_eligibility_rate": round(model_eligibility, 4),
                "model_status": "FINBERT" if cluster_rows else "NO_ELIGIBLE_MODEL_OUTPUT",
                "coverage_gaps": [value for value in ("openbb_yfinance", "sec_edgar", "finnhub_company") if value not in sources],
            },
        }


class NewsAdviceService:
    def __init__(self, news, evaluation, research, snapshot_root: Path) -> None:
        self.news, self.evaluation, self.research = news, evaluation, research
        self.snapshot_root = snapshot_root
        self.calculator = NewsFactorCalculator()

    def _history_counts(self, symbol: str, before: pd.Timestamp) -> list[float]:
        values: list[tuple[pd.Timestamp, float]] = []
        if not self.snapshot_root.exists():
            return []
        code = symbol.upper() if "." in symbol else f"US.{symbol.upper()}"
        for path in self.snapshot_root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                captured = _timestamp(payload.get("captured_at"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            feature = payload.get("features", {}).get(code)
            if payload.get("schema_version") == 3 and feature and captured < before:
                values.append((captured, float(feature.get("news_count", 0))))
        return [value for _, value in sorted(values)[-60:]]

    @staticmethod
    def _market_label(regime: str) -> str:
        return {"RISK_ON": "风险偏好", "NEUTRAL": "中性", "CAUTION": "谨慎", "RISK_OFF": "风险厌恶"}.get(regime, regime)

    @staticmethod
    def _research_guidance(response: dict[str, Any]) -> dict[str, Any]:
        """Headline-level interpretation; intentionally never changes the action layer."""
        items = [item for item in response.get("company_items", []) if not is_generic_sec_filing(str(item.get("title") or ""))]
        if not items:
            return {"status": "INSUFFICIENT", "bias": "NEUTRAL", "confidence": 0.0,
                    "summary": "没有可用于研究级解读的具体公司事件。", "catalysts": [], "risks": [],
                    "limitations": ["缺少可追溯的具体公司新闻，严格行动建议保持观望。"]}
        scored = [(item, float(item.get("analysis", {}).get("sentiment_score", 0))) for item in items]
        score = sum(value for _, value in scored) / len(scored)
        bias = "BULLISH" if score >= .12 else "BEARISH" if score <= -.12 else "NEUTRAL"
        methods = {str(item.get("analysis", {}).get("method")) for item, _ in scored}
        limitations = []
        if "FINBERT" not in methods: limitations.append("当前为标题级规则解读，尚无可用 FinBERT 方向证据。")
        if len({item.get("source_id") for item, _ in scored}) < 2: limitations.append("仅有单一来源或单一事件，尚未形成交叉确认。")
        return {"status": "RESEARCH", "bias": bias, "confidence": round(min(.70, .22 + .12 * len(items) + .12 * len({item.get('source_id') for item, _ in scored})), 3),
                "summary": "研究级解读仅用于识别催化剂与风险，不改变严格行动建议或总览分。",
                "catalysts": [item["title"] for item, value in scored if value >= .12][:3],
                "risks": [item["title"] for item, value in scored if value <= -.12][:3], "limitations": limitations}

    def advice(self, code: str, *, refresh: bool = False, as_of: str | None = None, response: dict[str, Any] | None = None) -> dict[str, Any]:
        if response is None:
            response = self.news.get_at(code, as_of, limit=100) if as_of else self.news.get(code, limit=100, refresh=refresh)
        now = _timestamp(as_of) if as_of else _timestamp(None)
        if as_of and len(str(as_of)) <= 10:
            now = _timestamp(f"{as_of}T21:00:00Z")
        factor = self.calculator.calculate(response, now.isoformat(), history_counts=self._history_counts(code, now))
        market = self.research.market_regime(response)
        validation = self.evaluation.evaluate(as_of=now.isoformat()) if as_of else self.evaluation.evaluate()
        source_status = str(response.get("source_status") or "UNAVAILABLE")
        fetched_at = response.get("fetched_at")
        stale = source_status in {"STALE_CACHE", "UNAVAILABLE", "COMPANY_UNAVAILABLE", "DISABLED"}
        if fetched_at:
            stale = stale or (now - _timestamp(fetched_at)).total_seconds() > 24 * 3600
        unavailable = source_status in {"UNAVAILABLE", "COMPANY_UNAVAILABLE", "DISABLED"} or not fetched_at
        validated = validation.get("status") == "VALIDATED"
        score, confidence = float(factor["factor_score"]), float(factor["confidence"])
        events = factor["events"]
        tradable = bool(factor["earliest_trade_at"] and _timestamp(factor["earliest_trade_at"]) <= now)
        positive = [row for row in events if float(row["direction"]) >= .15]
        negative = [row for row in events if float(row["direction"]) <= -.15]
        major_positive = any(row["high_impact"] and row["source_count"] >= 2 for row in positive)
        major_negative = any(row["high_impact"] and (row["source_count"] >= 2 or "sec_edgar" in row["sources"]) for row in negative)

        action = "HOLD"
        if validated and not stale and tradable and confidence >= .5 and events:
            if score >= .55 and confidence >= .70 and (major_positive or len(positive) >= 2) and market["regime"] != "RISK_OFF":
                action = "BUY"
            elif score >= .20 and confidence >= .55 and market["regime"] != "RISK_OFF" and not major_negative:
                action = "ACCUMULATE"
            elif score <= -.55 and confidence >= .70 and major_negative:
                action = "SELL"
            elif score <= -.20 and confidence >= .55:
                action = "REDUCE"

        contribution_points = 0.0
        if validated and not stale:
            if action in {"BUY", "ACCUMULATE"}:
                contribution_points = round(min(5.0, 5 * confidence * abs(score)), 2)
            elif action in {"REDUCE", "SELL"}:
                contribution_points = -round(min(15.0, 15 * confidence * abs(score)), 2)
        effect = "CONFIRM" if contribution_points > 0 else "DOWNGRADE" if contribution_points < 0 else "NONE"

        key_reasons = [f"{row['event_type']}：{row['title']}" for row in events[:3]]
        risk_flags: list[str] = []
        if stale:
            risk_flags.append("新闻缓存已过期，本次不参与总览决策。")
        if not validated:
            risk_flags.append("历史样本尚未通过样本外验证。")
        if events and not tradable:
            risk_flags.append(f"新闻最早可用于行动的时间为 {factor['earliest_trade_at']}。")
        if market["regime"] == "RISK_OFF":
            risk_flags.append("市场风险背景为风险厌恶，正面新闻行动被限制。")
        if major_negative:
            risk_flags.append("存在已确认的重大负面事件簇。")
        if not events:
            risk_flags.append("缺少可用于严格方向判断的 FinBERT 事件。")

        bias_text = {"BULLISH": "偏多", "BEARISH": "偏空", "NEUTRAL": "中性"}[factor["bias"]]
        if unavailable:
            reason = "公司新闻源不可用，本次保持观望且不参与总览决策。"
        elif stale:
            reason = f"新闻数据已过期，当前仅保留{bias_text}背景，不改变技术结论。"
        elif not events:
            reason = "近期新闻可追溯，但缺少合格的 FinBERT 方向证据，保持观望。"
        elif not validated:
            event_text = "、".join(dict.fromkeys(row["event_type"] for row in events[:2]))
            reason = f"历史样本尚未通过验证；近期新闻{bias_text}，主要来自{event_text or '可追溯事件'}，暂不改变技术结论。"
        elif not tradable:
            reason = f"近期新闻{bias_text}，但尚未到最早可行动时间，当前保持观望。"
        else:
            reason = f"近期 {len(events)} 个独立事件簇整体{bias_text}，市场背景为{self._market_label(market['regime'])}。"

        expires_at = (_timestamp(fetched_at) + timedelta(hours=24)).isoformat() if fetched_at else None
        status = "UNAVAILABLE" if unavailable else "STALE" if stale else "AVAILABLE" if events else "INSUFFICIENT_EVIDENCE"
        return {
            "symbol": str(response.get("symbol") or code).upper(),
            "as_of": now.isoformat(),
            "research_only": True,
            "factor_version": FACTOR_VERSION,
            "status": status,
            "action": action,
            "action_label": ACTION_LABEL[action],
            "position_guidance": ACTION_GUIDANCE[action],
            "bias": factor["bias"],
            "score": factor["factor_score"],
            "confidence": factor["confidence"],
            "validation_status": validation.get("status", "INSUFFICIENT_EVIDENCE"),
            "validation": validation,
            "concise_reason": reason,
            "components": factor["components"],
            "market_regime": market,
            "contribution": {
                "enabled": bool(contribution_points),
                "positive_cap": 5.0,
                "negative_cap": 15.0,
                "points": contribution_points,
                "effect": effect,
            },
            "research_guidance": self._research_guidance(response),
            "key_reasons": key_reasons,
            "risk_flags": risk_flags,
            "events": events,
            "evidence": factor["evidence"],
            "data_quality": {
                **factor["data_quality"],
                "source_status": source_status,
                "fetched_at": fetched_at,
                "is_cached": bool(response.get("is_cached")),
                "stale": stale,
                "warning": response.get("warning"),
            },
            "earliest_trade_at": factor["earliest_trade_at"],
            "expires_at": expires_at,
        }


def apply_news_overlay(base_action: str, base_strength: int, advice: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the capped asymmetric overlay to a long-only action ladder."""
    ladder = ["BUY", "ACCUMULATE", "HOLD", "REDUCE", "SELL"]
    advice = advice or {}
    requested = float(advice.get("contribution", {}).get("points", 0) or 0)
    requested = max(-15.0, min(5.0, requested))
    final_action, applied, effect = base_action, 0.0, "NONE"
    if requested > 0 and base_action in {"BUY", "ACCUMULATE"}:
        applied, effect = requested, "CONFIRM"
    elif requested < 0 and advice.get("action") in {"REDUCE", "SELL"}:
        index = ladder.index(base_action)
        final_action = ladder[min(len(ladder) - 1, index + 1)]
        applied = requested
        effect = "DOWNGRADE" if final_action != base_action else "CONFIRM"

    if not applied:
        final_strength = int(base_strength)
    else:
        final_is_bearish = final_action in {"REDUCE", "SELL"}
        aligned = (applied > 0 and final_action in {"BUY", "ACCUMULATE"}) or (applied < 0 and final_is_bearish)
        candidate = float(base_strength) + abs(applied) if aligned else float(base_strength) - abs(applied)
        floors = {"BUY": 70, "ACCUMULATE": 40, "HOLD": 20, "REDUCE": 40, "SELL": 70}
        final_strength = int(round(max(floors[final_action], min(100.0, candidate))))
    return {
        "base_action": base_action,
        "base_action_strength": int(base_strength),
        "action": final_action,
        "action_strength": final_strength,
        "requested_points": round(requested, 2),
        "applied_points": round(applied, 2),
        "effect": effect,
    }
