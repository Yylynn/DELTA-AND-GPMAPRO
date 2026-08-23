from app.services.news_research import NewsResearchService
from app.services.news import NewsService


class Alerts:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot or {"active_alerts": [], "last_check": None}

    def snapshot(self):
        return self._snapshot


def article(*, scope="COMPANY", direction="BULLISH", score=.7, high_impact=False, source="openbb_yfinance"):
    return {"id": f"{scope}-{direction}", "title": "Documented event", "source": source, "source_id": source,
            "published_at": "2026-08-20T10:00:00Z", "url": "https://example.com/article", "entity_matches": ["apple"],
            "analysis": {"event_type": "GUIDANCE", "direction": direction, "sentiment_score": score, "high_impact": high_impact, "method": "FINBERT"}}


def test_company_coverage_gap_is_not_presented_as_neutral():
    card = NewsResearchService(None, Alerts()).company_card({"symbol": "US.AAPL", "company_items": [], "source_status": "NO_COMPANY_NEWS", "fetched_at": "2026-08-20T10:00:00Z"})
    assert card["coverage_status"] == "COVERAGE_GAP"
    assert card["assessment"] == "INSUFFICIENT"
    assert card["sentiment_score"] is None


def test_company_card_keeps_only_company_evidence_and_traces_risk():
    company = article(direction="BEARISH", score=-.8, high_impact=True)
    market = article(scope="MARKET", source="cnbc")
    card = NewsResearchService(None, Alerts()).company_card({"symbol": "US.AAPL", "company_items": [company], "market_items": [market], "source_status": "LIVE", "fetched_at": "2026-08-20T10:00:00Z"})
    assert card["coverage_status"] == "AVAILABLE"
    assert card["assessment"] == "NEGATIVE"
    assert card["risk_items"] == [company["id"]]
    assert [item["id"] for item in card["event_timeline"]] == [company["id"]]


def test_market_regime_uses_cross_source_news_and_volatility_validation():
    cnbc = article(scope="MARKET", direction="BEARISH", score=-.6, source="cnbc")
    mw = {**article(scope="MARKET", direction="BEARISH", score=-.6, source="marketwatch"), "id": "marketwatch-1"}
    alerts = Alerts({"active_alerts": [{"severity": "RISK"}], "last_check": {"status": "OK"}})
    result = NewsResearchService(None, alerts).market_regime({"market_items": [cnbc, mw], "fetched_at": "2026-08-20T10:00:00Z"})
    assert result["regime"] == "RISK_OFF"
    assert result["cross_source_confirmation"] == 2
    assert result["volatility_validation"]["status"] == "AVAILABLE"


def test_market_regime_degrades_confidence_without_volatility_check():
    result = NewsResearchService(None, Alerts()).market_regime({"market_items": [], "fetched_at": None})
    assert result["regime"] == "NEUTRAL"
    assert result["volatility_validation"]["status"] == "UNAVAILABLE"
    assert result["confidence"] < .4


def test_research_api_exposes_company_and_market_cards(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app.api.news as news_api
    from app.main import app

    class Provider:
        def company_news(self, symbol, limit):
            return [{"title": "Apple raises guidance", "date": "2026-08-20T10:00:00Z", "source": "Example", "url": "https://example.com/aapl"}]

        def market_news(self, limit):
            return [], []

    service = NewsService(tmp_path, provider=Provider())
    service.analyzer._attempted = True  # Keep the API schema test fully local and deterministic.
    monkeypatch.setattr(news_api, "news_service", service)
    monkeypatch.setattr(news_api, "research_service", NewsResearchService(service, Alerts()))
    response = TestClient(app).get("/api/news/US.AAPL/research")
    assert response.status_code == 200
    assert set(response.json()) == {"company", "market", "snapshot_id"}
    assert response.json()["company"]["coverage_status"] == "AVAILABLE"
    assert list((tmp_path.parent / "news_research_history" / "US_AAPL").glob("*.json"))
