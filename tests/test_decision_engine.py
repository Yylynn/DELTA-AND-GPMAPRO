from app.services.decision_engine import DecisionEngine


def item(id, source, category, direction, status="ACTIVE", confidence=.8):
    return {"id": id, "source": source, "category": category, "label": id, "direction": direction, "strength": .8, "confidence": confidence, "weight": 1, "status": status, "as_of": "2025-06-30", "details": {}}


def snapshot(*items, balance="BULLISH", bull=.70, bear=.10, confidence=.75, freshness="CURRENT", conflicts=None):
    return {"symbol": "AAPL", "timeframe": "1d", "as_of": "2025-06-30", "evidence_balance": balance, "scores": {"bullish": bull, "bearish": bear, "neutral": max(0, 1-bull-bear)}, "confidence": confidence, "evidence": list(items), "conflicts": conflicts or [], "data_quality": {"freshness": freshness}}


def test_buy_requires_multiple_independent_confirmations():
    s = snapshot(item("delta", "DELTA", "TIME", "BULLISH"), item("gpmapro_trend", "GPMAPRO", "TREND", "BULLISH"), item("gpmapro_b1", "GPMAPRO", "SIGNAL", "BULLISH"), item("volume", "VOLUME", "PRICE_VOLUME", "BULLISH"))
    result = DecisionEngine().decide(s)
    assert result["state"] == "BUY" and result["confirmations"]["count"] == 4


def test_b_signal_alone_cannot_be_buy():
    result = DecisionEngine().decide(snapshot(item("gpmapro_b1", "GPMAPRO", "SIGNAL", "BULLISH"), bull=.7))
    assert result["state"] == "WATCH"


def test_bearish_structure_requires_more_than_one_signal_for_risk():
    one = DecisionEngine().decide(snapshot(item("gpmapro_s1", "GPMAPRO", "SIGNAL", "BEARISH"), balance="BEARISH", bull=.1, bear=.7))
    two = DecisionEngine().decide(snapshot(item("gpmapro_trend", "GPMAPRO", "TREND", "BEARISH"), item("volume", "VOLUME", "PRICE_VOLUME", "BEARISH"), balance="BEARISH", bull=.1, bear=.7))
    assert one["state"] != "RISK" and two["state"] == "RISK"


def test_insufficient_and_very_stale_are_wait_not_buy():
    assert DecisionEngine().decide(snapshot(balance="INSUFFICIENT"))["state"] == "WAIT"
    assert DecisionEngine().decide(snapshot(item("delta", "DELTA", "TIME", "BULLISH"), freshness="VERY_STALE"))["state"] == "WAIT"


def test_conflict_prevents_buy_and_low_confidence_is_watch():
    conflicted = snapshot(item("delta", "DELTA", "TIME", "BULLISH"), item("gpmapro_trend", "GPMAPRO", "TREND", "BEARISH"), item("gpmapro_b1", "GPMAPRO", "SIGNAL", "BULLISH"), item("volume", "VOLUME", "PRICE_VOLUME", "BULLISH"), conflicts=[{"type": "DIRECTION_CONFLICT"}])
    assert DecisionEngine().decide(conflicted)["state"] == "WATCH"
    assert DecisionEngine().decide(snapshot(item("delta", "DELTA", "TIME", "BULLISH"), item("gpmapro_trend", "GPMAPRO", "TREND", "BULLISH"), item("gpmapro_b1", "GPMAPRO", "SIGNAL", "BULLISH"), confidence=.52))["state"] == "WATCH"


def test_historical_small_sample_and_expired_signal_do_not_confirm():
    result = DecisionEngine().decide(snapshot(item("gpmapro_b1", "GPMAPRO", "SIGNAL", "BULLISH", "EXPIRED"), item("backtest", "BACKTEST", "HISTORICAL", "BULLISH", confidence=.2)))
    assert result["confirmations"]["count"] == 0 and result["state"] != "BUY"


def test_is_deterministic_and_schema_complete():
    s = snapshot(item("delta", "DELTA", "TIME", "BULLISH"), item("gpmapro_trend", "GPMAPRO", "TREND", "BULLISH"))
    first, second = DecisionEngine().decide(s), DecisionEngine().decide(s)
    assert first == second
    assert set(first) == {"symbol", "timeframe", "as_of", "state", "confidence", "scores", "evidence_balance", "confirmations", "reasons", "missing_conditions", "risk_factors", "data_quality", "decision_trace", "news_trace"}
