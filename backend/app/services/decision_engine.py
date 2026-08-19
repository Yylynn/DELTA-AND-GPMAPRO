"""Deterministic research-state classifier operating exclusively on evidence."""
from __future__ import annotations

from app.config.decision_config import DECISION_CONFIG, DecisionConfig
from app.models.decision import DecisionSnapshot


class DecisionEngine:
    def __init__(self, config: DecisionConfig = DECISION_CONFIG): self.config = config

    @staticmethod
    def _active(items: list[dict], **match: str) -> list[dict]:
        return [item for item in items if item.get("status") in {"ACTIVE", "RECENT", "AVAILABLE"} and all(item.get(key) == value for key, value in match.items())]

    def decide(self, snapshot: dict) -> dict:
        items, scores = snapshot.get("evidence", []), snapshot.get("scores", {})
        bullish, bearish = float(scores.get("bullish", 0)), float(scores.get("bearish", 0))
        balance, evidence_conf = snapshot.get("evidence_balance", "INSUFFICIENT"), float(snapshot.get("confidence", 0))
        freshness = snapshot.get("data_quality", {}).get("freshness", "UNKNOWN")
        delta = bool(self._active(items, source="DELTA", category="TIME", direction="BULLISH"))
        trend = bool(self._active(items, id="gpmapro_trend", direction="BULLISH"))
        signal = bool(self._active(items, source="GPMAPRO", category="SIGNAL", direction="BULLISH"))
        volume = bool(self._active(items, source="VOLUME", category="PRICE_VOLUME", direction="BULLISH"))
        historical = bool([x for x in self._active(items, source="BACKTEST", category="HISTORICAL", direction="BULLISH") if float(x.get("confidence", 0)) >= self.config.historical_min_confidence])
        news_trace = snapshot.get("news_trace", {})
        news_company = news_trace.get("company", {})
        news_market = news_trace.get("market", {})
        news_confirmed = bool(news_trace.get("status") == "AVAILABLE" and news_company.get("confirmation_eligible") and news_company.get("direction") == "BULLISH" and not news_trace.get("high_risk"))
        news_adverse = news_trace.get("status") == "AVAILABLE" and (bool(news_trace.get("high_risk")) or (news_company.get("confirmation_eligible") and news_company.get("direction") == "BEARISH") or (news_market.get("confirmation_eligible") and news_market.get("direction") == "BEARISH"))
        confirms = {"delta": delta, "trend": trend, "signal": signal, "volume": volume, "historical": historical, "news": news_confirmed}
        # BUY thresholds intentionally exclude NEWS: a headline cannot replace
        # a missing technical/time confirmation.
        count = sum(value for key, value in confirms.items() if key != "news")
        bearish_trend = bool(self._active(items, id="gpmapro_trend", direction="BEARISH"))
        bearish_signal = bool(self._active(items, source="GPMAPRO", category="SIGNAL", direction="BEARISH"))
        adverse_volume = bool(self._active(items, source="VOLUME", category="PRICE_VOLUME", direction="BEARISH"))
        bearish_delta = bool(self._active(items, source="DELTA", category="TIME", direction="BEARISH"))
        bearish_historical = bool(self._active(items, source="BACKTEST", category="HISTORICAL", direction="BEARISH"))
        bear_count = sum((bearish_trend, bearish_signal, adverse_volume, bearish_delta, bearish_historical))
        conflicts = snapshot.get("conflicts", [])
        critical_conflict = bool(conflicts and (bearish_trend or bearish_signal or adverse_volume))
        stale = freshness in {"STALE", "VERY_STALE", "UNKNOWN"}
        penalty = self.config.very_stale_confidence_penalty if freshness in {"VERY_STALE", "UNKNOWN"} else self.config.stale_confidence_penalty if freshness == "STALE" else 1.0
        if conflicts: penalty *= self.config.conflict_confidence_penalty
        separation = abs(bullish - bearish)
        decision_confidence = min(1, evidence_conf * (0.70 + .06 * min(count, 5) + .08 * min(separation, 1)) * penalty)
        buy_requirements = {"balance_bullish": balance == "BULLISH", "confidence": evidence_conf >= self.config.buy_min_confidence, "score": bullish >= self.config.buy_min_bullish_score, "score_spread": bullish - bearish >= self.config.buy_min_score_spread, "confirmations": count >= self.config.buy_min_confirmations}
        if not delta and self.config.flexible_delta_mode:
            buy_requirements["confidence"] = buy_requirements["confidence"] and evidence_conf >= self.config.no_delta_min_confidence
            buy_requirements["score"] = buy_requirements["score"] and bullish >= self.config.no_delta_min_bullish_score
            buy_requirements["structural_without_delta"] = trend and signal and volume
        risk_requirements = {"balance_bearish": balance == "BEARISH", "confidence": evidence_conf >= self.config.risk_min_confidence, "score": bearish >= self.config.risk_min_bearish_score, "confirmations": bear_count >= self.config.risk_min_confirmations}
        reasons, missing, risks = [], [], []
        if delta: reasons.append("DELTA_BULLISH_WINDOW: bullish DELTA timing window is active.")
        if trend: reasons.append("TREND_BULLISH: GPMAPRO trend is bullish.")
        if signal: reasons.append("BULLISH_SIGNAL_ACTIVE: active or recent bullish GPMAPRO signal is present.")
        if volume: reasons.append("VOLUME_CONFIRMED: price advance is supported by high volume.")
        if historical: reasons.append("HISTORICAL_SUPPORT: point-in-time historical evidence is positive.")
        if bearish_trend: risks.append({"code": "TREND_BEARISH", "severity": "HIGH", "message": "GPMAPRO trend evidence is bearish."})
        if bearish_signal: risks.append({"code": "BEARISH_SIGNAL_ACTIVE", "severity": "MEDIUM", "message": "An active or recent bearish GPMAPRO signal is present."})
        if adverse_volume: risks.append({"code": "VOLUME_ADVERSE", "severity": "HIGH", "message": "Price decline is confirmed by high volume."})
        if conflicts: risks.append({"code": "EVIDENCE_CONFLICT", "severity": "MEDIUM", "message": "Independent evidence sources have conflicting directions."})
        if news_adverse: risks.append({"code": "NEWS_ADVERSE", "severity": "HIGH" if news_trace.get("high_risk") else "MEDIUM", "message": "新闻证据存在负面催化剂或明显负面情绪。"})
        if stale: risks.append({"code": "DATA_STALE", "severity": "HIGH" if freshness in {"VERY_STALE", "UNKNOWN"} else "MEDIUM", "message": "Decision confidence is degraded by data freshness."})
        if freshness in {"VERY_STALE", "UNKNOWN"}: state = "RISK" if all(risk_requirements.values()) else "WAIT"; missing.append("DATA_STALE: data is not current enough for a research candidate.")
        elif balance == "INSUFFICIENT": state = "WAIT"; missing.append("INSUFFICIENT_EVIDENCE: evidence is insufficient.")
        elif all(risk_requirements.values()): state = "RISK"
        elif all(buy_requirements.values()) and not critical_conflict: state = "BUY"
        elif bullish >= self.config.watch_min_bullish_score or balance in {"BULLISH", "MIXED"} or critical_conflict: state = "WATCH"
        else: state = "WAIT"
        # News is a confirmation/veto layer, never a standalone entry signal.
        if state == "BUY" and news_adverse:
            state = "WATCH"
            missing.append("NEWS_VETO: 负面新闻证据阻止形成 BUY。")
        if news_confirmed:
            reasons.append("NEWS_CONFIRMED: 已授权白名单新闻与当前技术方向一致。")
        if state != "BUY":
            if not signal: missing.append("No active bullish technical signal.")
            if not volume: missing.append("Volume confirmation is neutral or absent.")
            if not historical: missing.append("Historical support is unavailable or below the sample-confidence threshold.")
            if count < self.config.buy_min_confirmations: missing.append(f"Only {count}/{self.config.buy_min_confirmations} required confirmations are present.")
            if critical_conflict: missing.append("Critical directional conflict prevents a research candidate.")
        trace = {"hard_gates": {"data_valid": freshness not in {"VERY_STALE", "UNKNOWN"}, "evidence_sufficient": balance != "INSUFFICIENT", "critical_conflict": critical_conflict}, "buy_conditions": buy_requirements, "risk_conditions": risk_requirements, "confirmation_count": count, "bearish_confirmation_count": bear_count}
        trace["news"] = {"status": news_trace.get("status", "UNAVAILABLE"), "confirmed": news_confirmed, "vetoed": state == "WATCH" and news_adverse}
        return DecisionSnapshot(symbol=snapshot["symbol"], timeframe=snapshot["timeframe"], as_of=snapshot["as_of"], state=state, confidence=round(decision_confidence, 4), scores=scores, evidence_balance=balance, confirmations={**confirms, "count": count}, reasons=reasons, missing_conditions=list(dict.fromkeys(missing)), risk_factors=risks, data_quality=snapshot.get("data_quality", {}), decision_trace=trace, news_trace=news_trace).model_dump()
