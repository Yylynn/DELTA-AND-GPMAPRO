from datetime import datetime, timezone

import pandas as pd

from app.services.news_factor import NewsFactorService


class StubNews:
    def source_health(self):
        return []

    def get(self, code: str, *, limit: int, refresh: bool):
        return {
            "symbol": code,
            "items": [{
                "id": "article-1", "title": "Apple raises guidance", "url": "https://example.com/aapl",
                "publisher": "Example", "published_at": datetime.now(timezone.utc).isoformat(),
                "scope": "COMPANY", "entity_status": "ACCEPTED", "entity_matches": ["apple"],
                "factor_eligible": True, "earliest_trade_at": "2026-08-24T09:30:00-04:00",
                "analysis": {"method": "FINBERT", "sentiment_score": .8, "event_type": "GUIDANCE", "direction": "BULLISH", "high_impact": True},
            }],
            "market_items": [
                {"id": "macro-1", "scope": "MARKET", "source_id": "cnbc", "published_at": datetime.now(timezone.utc).isoformat(), "analysis": {"sentiment_score": -.8}},
                {"id": "macro-2", "scope": "MARKET", "source_id": "marketwatch", "published_at": datetime.now(timezone.utc).isoformat(), "analysis": {"sentiment_score": -.8}},
            ],
        }


def test_news_factor_snapshot_ranks_point_in_time_company_news(tmp_path) -> None:
    imported = tmp_path / "imported"; imported.mkdir()
    dates = pd.bdate_range("2025-01-01", periods=140)
    pd.DataFrame({"date": dates, "open": range(100, 240), "high": range(101, 241), "low": range(99, 239), "close": range(100, 240), "volume": [1_000_000] * len(dates)}).to_csv(imported / "AAPL.csv", index=False)
    service = NewsFactorService(StubNews(), tmp_path / "news_cache")
    snapshot = service.snapshot(refresh=False)
    duplicate = service.snapshot(refresh=False)
    result = service.candidates()
    assert snapshot["symbols_captured"] == 30
    assert snapshot["schema_version"] == 3
    assert duplicate["snapshot_id"] == snapshot["snapshot_id"]
    assert duplicate["idempotent"] is True
    assert result["status"] == "RESEARCH_ONLY"
    assert result["candidates"][0]["symbol"] == "US.AAPL"
    assert result["candidates"][0]["news_score"] > 0
    assert result["candidates"][0]["earliest_trade_at"]
    assert result["market_risk_filter"]["status"] == "RED"
    assert result["candidates"][0]["tier"] == "FILTERED"
