from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.config.news_sources import enabled_sources, source_catalog
from app.services.news import NewsService, PublicRssNewsProvider, normalize_records, provider_symbol
from app.services.decision_engine import DecisionEngine


class FakeProvider:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows or []
        self.error = error
        self.calls = 0

    def company_news(self, symbol: str, limit: int):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


NOW = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)


def test_provider_symbol_supports_us_and_hk() -> None:
    assert provider_symbol("US.AAPL") == "AAPL"
    assert provider_symbol("HK.00700") == "0700.HK"


def test_free_source_registry_enables_only_configured_sources() -> None:
    catalog = {item["source_id"]: item for item in source_catalog()}
    assert catalog["cnbc"]["enabled"] and catalog["cnbc"]["rss_url"].startswith("https://")
    assert catalog["marketwatch"]["enabled"] and catalog["marketwatch"]["collector"] == "RSS"
    assert catalog["wallstreetcn"]["enabled"] and catalog["wallstreetcn"]["rss_url"] == "https://dedicated.wallstreetcn.com/rss.xml"
    assert {
        "reuters", "bloomberg", "simuwang", "barclayhedge", "bridgewater", "morningstar",
        "eastmoney", "stcn", "10jqka", "xueqiu", "jiemian",
    }.isdisjoint(catalog)
    assert {source.source_id for source in enabled_sources(cnbc=False)} == {"marketwatch", "wallstreetcn", "openbb_yfinance", "sec_edgar", "finnhub_company"}


def test_rss_parser_preserves_source_scope_and_published_time(monkeypatch) -> None:
    class Response:
        content = b"<rss><channel><item><title>Market headline</title><link>https://example.com/news</link><pubDate>Tue, 19 Aug 2026 12:00:00 GMT</pubDate></item></channel></rss>"
        def raise_for_status(self): pass
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get(self, url): return Response()
    monkeypatch.setattr("app.services.news.httpx.Client", lambda **_: Client())
    rows, warnings = PublicRssNewsProvider(enabled_sources()).market_news(10)
    assert not warnings and {row["source"] for row in rows} == {"CNBC", "MarketWatch", "华尔街见闻"}
    assert all(row["scope"] == "MARKET" and row["date"] for row in rows)


def test_normalize_records_dedupes_sorts_and_tolerates_missing_fields() -> None:
    records = normalize_records([
        {"title": "Older", "date": "2026-08-18T09:00:00+08:00", "url": "https://example.com/old", "source": "Example"},
        {"title": "Latest", "date": "2026-08-19T09:00:00+08:00", "url": "https://example.com/new", "source": "Example", "description": "Details"},
        {"title": "Latest", "date": "2026-08-19T09:00:00+08:00", "url": "https://example.com/new", "source": "Example"},
        {"title": "No link or time"},
        {"title": ""},
    ], "US.AAPL")
    assert [item["title"] for item in records] == ["Latest", "Older", "No link or time"]
    assert records[0]["summary"] == "Details"
    assert records[-1]["url"] is None and records[-1]["published_at"] is None


def test_news_service_uses_fresh_cache_and_force_refresh(tmp_path) -> None:
    provider = FakeProvider([{"title": "AAPL news", "date": "2026-08-19T07:30:00Z", "source": "TheStreet", "url": "https://example.com/aapl"}])
    service = NewsService(tmp_path, provider=provider, now=lambda: NOW)
    first = service.get("US.AAPL")
    cached = service.get("US.AAPL")
    forced = service.get("US.AAPL", refresh=True)
    assert first["source_status"] == "LIVE"
    assert cached["source_status"] == "CACHED"
    assert forced["source_status"] == "LIVE"
    assert provider.calls == 2


def test_news_service_keeps_only_user_approved_enabled_sources_and_exposes_audit(tmp_path) -> None:
    service = NewsService(tmp_path, provider=FakeProvider([
        {"title": "AAPL Approved", "date": "2026-08-19T07:30:00Z", "source": "TheStreet", "url": "https://example.com/approved"},
        {"title": "Unrelated company item", "date": "2026-08-19T07:31:00Z", "source": "Unknown Publisher", "url": "https://example.com/dropped"},
    ]), now=lambda: NOW)
    result = service.get("US.AAPL")
    assert [item["source_id"] for item in result["items"]] == ["openbb_yfinance"]
    assert result["items"][0]["entity_status"] == "ACCEPTED"
    assert result["dropped_unapproved_sources"] == []
    insight = service.insight("US.AAPL")
    assert insight["status"] == "AVAILABLE"
    assert insight["citations"][0]["url"] == "https://example.com/approved"


def test_market_news_is_separate_from_company_news_and_needs_cross_source_confirmation(tmp_path) -> None:
    class MixedProvider(FakeProvider):
        def market_news(self, limit: int):
            return [
                {"title": "Macro risk", "date": "2026-08-19T07:30:00Z", "source": "CNBC", "scope": "MARKET"},
                {"title": "Macro risk", "date": "2026-08-19T07:31:00Z", "source": "MarketWatch", "scope": "MARKET"},
            ], []
    service = NewsService(tmp_path, provider=MixedProvider([{"title": "AAPL company item", "date": "2026-08-19T07:30:00Z", "source": "TheStreet"}]), now=lambda: NOW)
    trace = service.insight("US.AAPL") if service.get("US.AAPL") else None
    assert trace["company"]["source_count"] == 1 and not trace["company"]["confirmation_eligible"]
    assert trace["market"]["source_count"] == 2 and trace["market"]["confirmation_eligible"]


def test_company_failure_never_uses_macro_rss_as_a_symbol_news_fallback(tmp_path) -> None:
    class CompanyFailureWithMacro(FakeProvider):
        def __init__(self): super().__init__(error=RuntimeError("OpenBB provider unavailable"))
        def market_news(self, limit: int):
            return [{"title": "Fed policy update", "date": "2026-08-19T07:30:00Z", "source": "CNBC", "scope": "MARKET"}], []

    result = NewsService(tmp_path, provider=CompanyFailureWithMacro(), now=lambda: NOW).get("US.AAPL")
    assert result["source_status"] == "COMPANY_UNAVAILABLE"
    assert result["items"] == result["company_items"] == []
    assert [item["title"] for item in result["market_items"]] == ["Fed policy update"]
    assert "不会代替 AAPL 的公司新闻" in result["warning"]
    company_health = next(item for item in result["source_health"] if item["source_id"] == "openbb_yfinance")
    assert company_health["availability"] == "UNAVAILABLE"
    assert company_health["availability_reason"] == "OpenBB provider unavailable"


def test_empty_company_result_has_an_explicit_company_news_message(tmp_path) -> None:
    class MacroOnly(FakeProvider):
        def market_news(self, limit: int):
            return [{"title": "Macro headline", "date": "2026-08-19T07:30:00Z", "source": "CNBC", "scope": "MARKET"}], []

    result = NewsService(tmp_path, provider=MacroOnly(), now=lambda: NOW).get("US.AAPL")
    assert result["source_status"] == "NO_COMPANY_NEWS"
    assert result["company_items"] == [] and len(result["market_items"]) == 1
    assert "未返回 AAPL 的可验证公司新闻" in result["warning"]


def test_news_service_returns_stale_cache_when_provider_fails(tmp_path) -> None:
    good = FakeProvider([{"title": "AAPL Cached item", "date": "2026-08-19T07:30:00Z", "source": "TheStreet"}])
    clock = [NOW]
    service = NewsService(tmp_path, ttl_seconds=0, provider=good, now=lambda: clock[0])
    service.get("US.AAPL")
    clock[0] = NOW.replace(second=1)
    service.provider = FakeProvider(error=RuntimeError("upstream down"))
    result = service.get("US.AAPL")
    assert result["source_status"] == "STALE_CACHE"
    assert result["is_cached"] is True
    assert result["items"][0]["title"] == "AAPL Cached item"


def test_news_service_without_cache_has_readable_unavailable_status(tmp_path) -> None:
    service = NewsService(tmp_path, provider=FakeProvider(error=RuntimeError("upstream down")), now=lambda: NOW)
    result = service.get("US.AAPL")
    assert result["source_status"] == "UNAVAILABLE"
    assert result["items"] == []
    assert "新闻源暂时不可用" in result["warning"]


def test_news_api_validates_code_and_returns_service_schema(monkeypatch, tmp_path) -> None:
    import app.api.news as news_api

    service = NewsService(tmp_path, provider=FakeProvider([{"title": "AAPL news", "date": "2026-08-19T07:30:00Z", "source": "TheStreet"}]), now=lambda: NOW)
    monkeypatch.setattr(news_api, "news_service", service)
    client = TestClient(app)
    response = client.get("/api/news/US.AAPL?limit=5")
    assert response.status_code == 200
    assert {"symbol", "provider_symbol", "items", "company_items", "market_items", "source_status", "fetched_at", "is_cached", "warning", "dropped_unapproved_sources", "source_warnings", "source_health"} == set(response.json())
    invalid = client.get("/api/news/SH.600519")
    assert invalid.status_code == 422


def test_adverse_news_vetoes_a_buy_but_never_creates_a_buy() -> None:
    snapshot = {
        "symbol": "AAPL", "timeframe": "1d", "as_of": "2026-08-19", "evidence_balance": "BULLISH",
        "confidence": .8, "scores": {"bullish": .8, "bearish": .1}, "conflicts": [], "data_quality": {"freshness": "FRESH"},
        "evidence": [
            {"source": "DELTA", "category": "TIME", "direction": "BULLISH", "status": "ACTIVE"},
            {"id": "gpmapro_trend", "source": "GPMAPRO", "category": "TREND", "direction": "BULLISH", "status": "AVAILABLE"},
            {"source": "GPMAPRO", "category": "SIGNAL", "direction": "BULLISH", "status": "ACTIVE"},
            {"source": "VOLUME", "category": "PRICE_VOLUME", "direction": "BULLISH", "status": "AVAILABLE"},
            {"source": "BACKTEST", "category": "HISTORICAL", "direction": "BULLISH", "status": "AVAILABLE", "confidence": .8},
        ],
        "news_trace": {"status": "AVAILABLE", "company": {"direction": "BEARISH"}, "high_risk": [{"id": "n1", "source": "TheStreet", "title": "Adverse event", "published_at": "2026-08-19T20:00:00Z", "url": "https://example.com/n1"}], "citations": []},
    }
    decision = DecisionEngine().decide(snapshot)
    assert decision["state"] == "WATCH"
    assert decision["news_trace"]["high_risk"][0]["source"] == "TheStreet"
