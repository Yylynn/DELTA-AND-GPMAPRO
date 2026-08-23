from datetime import date, timedelta
import pandas as pd

from app.services.evidence_engine import EvidenceEngine


def bars(count=80):
    dates = pd.date_range("2025-01-01", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), dtype=float)
    return pd.DataFrame({"date": dates, "open": close - .5, "high": close + 1, "low": close - 1, "close": close, "volume": [1000] * (count - 1) + [1500]})


def test_snapshot_has_stable_research_contract_and_no_trade_action():
    snapshot = EvidenceEngine().snapshot(bars(), "aapl", "1d")
    assert set(snapshot) == {"symbol", "timeframe", "as_of", "evidence_balance", "scores", "confidence", "evidence", "conflicts", "data_quality", "news_trace", "summary"}
    assert snapshot["evidence_balance"] in {"BULLISH", "BEARISH", "BALANCED", "MIXED", "INSUFFICIENT"}
    assert {item["source"] for item in snapshot["evidence"]} >= {"GPMAPRO", "VOLUME", "DATA"}
    assert all("BUY" not in line and "SELL" not in line for line in snapshot["summary"])


def test_as_of_prevents_future_evidence_leakage():
    source = bars(100); cutoff = str(source.date.iloc[60].date()); engine = EvidenceEngine()
    expected = engine.snapshot(source, "x", "1d", cutoff)
    changed = source.copy(); changed.loc[61:, ["open", "high", "low", "close", "volume"]] *= 20
    assert engine.snapshot(changed, "x", "1d", cutoff) == expected


def test_expired_signals_are_retained_for_detail_but_not_scored():
    snapshot = EvidenceEngine().snapshot(bars(), "x", "1d")
    expired = [item for item in snapshot["evidence"] if item["status"] == "EXPIRED"]
    assert all(item["category"] == "SIGNAL" for item in expired)


def test_historical_confidence_is_sample_size_bounded():
    assert EvidenceEngine._sample_confidence(3) == .20
    assert EvidenceEngine._sample_confidence(5) == .40
    assert EvidenceEngine._sample_confidence(10) == .65
    assert EvidenceEngine._sample_confidence(30) == .85
