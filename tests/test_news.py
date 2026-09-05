from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import time

from fastapi.testclient import TestClient

from app.main import app
from app.config.news_sources import enabled_sources, source_catalog
from app.services.news import NewsService, PublicRssNewsProvider, build_market_headlines, normalize_records, provider_symbol
from app.config.news_universe import entity_terms
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
    assert catalog["cointelegraph"]["enabled"] and catalog["cointelegraph"]["allow_summary"] is False
    assert catalog["decrypt"]["enabled"] and catalog["theblock"]["enabled"]
    assert catalog["chaincatcher"]["enabled"] is False and catalog["chaincatcher"]["authorization"] == "PENDING_APPROVAL"
    assert catalog["cointelegraph"]["allowed_fields"] == ["title", "url", "published_at", "thumbnail"]
    assert {
        "reuters", "bloomberg", "simuwang", "barclayhedge", "bridgewater", "morningstar",
        "eastmoney", "stcn", "10jqka", "xueqiu", "jiemian",
    }.isdisjoint(catalog)
    assert {"marketwatch", "wallstreetcn", "fed_press", "treasury_press", "coindesk", "cointelegraph", "decrypt", "theblock", "openbb_yfinance", "sec_edgar", "finnhub_company"} == {source.source_id for source in enabled_sources(cnbc=False)}


def test_rss_parser_preserves_source_scope_and_published_time(monkeypatch) -> None:
    class Response:
        content = b"<rss xmlns:media='http://search.yahoo.com/mrss/'><channel><item><title>Market headline</title><link>https://example.com/news</link><pubDate>Tue, 19 Aug 2026 12:00:00 GMT</pubDate><media:thumbnail url='https://example.com/image.jpg'/></item></channel></rss>"
        def raise_for_status(self): pass
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get(self, url): return Response()
    monkeypatch.setattr("app.services.news.httpx.Client", lambda **_: Client())
    rows, warnings = PublicRssNewsProvider(enabled_sources()).market_news(10)
    assert not warnings and {row["source"] for row in rows} == {"CNBC", "MarketWatch", "华尔街见闻", "Federal Reserve", "U.S. Treasury", "CoinDesk", "Cointelegraph", "Decrypt", "The Block"}
    assert all(row["scope"] == "MARKET" and row["date"] for row in rows)
    assert all(row["image"] == "https://example.com/image.jpg" for row in rows)


def test_market_headlines_are_grouped_by_source_and_combined_is_diverse() -> None:
    items = [
        {"id": f"w{index}", "source_id": "wallstreetcn", "published_at": f"2026-08-19T0{9-index}:00:00Z"}
        for index in range(5)
    ] + [
        {"id": "c1", "source_id": "cnbc", "published_at": "2026-08-19T08:30:00Z"},
        {"id": "m1", "source_id": "marketwatch", "published_at": "2026-08-19T08:20:00Z"},
        {"id": "f1", "source_id": "fed_press", "published_at": "2026-08-19T08:10:00Z"},
        {"id": "d1", "source_id": "coindesk", "published_at": "2026-08-19T08:00:00Z"},
    ]
    result = build_market_headlines(items, [])
    groups = {group["id"]: group for group in result["headline_groups"]}
    assert result["source_order"] == ["all", "wallstreetcn", "cnbc", "marketwatch", "official", "coindesk", "crypto"]
    assert [item["id"] for item in groups["wallstreetcn"]["items"]] == ["w0", "w1", "w2", "w3", "w4"]
    assert len({item["source_id"] for item in groups["all"]["items"][:5]}) == 5
    assert [item["id"] for item in groups["official"]["items"]] == ["f1"]


def test_market_rss_metadata_is_redacted_but_retains_audit_fields(tmp_path) -> None:
    class Provider(FakeProvider):
        def market_news(self, limit: int):
            return [{"title": "Bitcoin market update", "date": "2026-08-19T07:30:00Z", "source": "Cointelegraph", "url": "https://example.com/article", "summary": "RSS description must not be stored", "image": "https://example.com/image.jpg", "scope": "MARKET"}], []

    result = NewsService(tmp_path, provider=Provider(), now=lambda: NOW).get_market(refresh=True)
    item = result["market_items"][0]
    assert item["source_id"] == "cointelegraph"
    assert item["summary"] is None
    assert item["url"] == "https://example.com/article"
    assert item["thumbnail"] == "https://example.com/image.jpg"
    assert item["allowed_fields"] == ["title", "url", "published_at", "thumbnail"]
    assert item["factor_eligible"] is False


def test_concurrent_market_refresh_fetches_upstream_once(tmp_path) -> None:
    class SlowMacro(FakeProvider):
        def market_news(self, limit: int):
            self.calls += 1; time.sleep(.05)
            return [{"title": "Macro", "date": "2026-08-19T08:00:00Z", "source": "CNBC", "scope": "MARKET"}], []
    provider = SlowMacro(); service = NewsService(tmp_path, provider=provider, now=lambda: NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.get_market(refresh=True), range(2)))
    assert provider.calls == 1
    assert {item["source_status"] for item in results} == {"LIVE", "CACHED"}


def test_all_market_sources_failing_preserves_last_successful_cache(tmp_path) -> None:
    class Macro(FakeProvider):
        def market_news(self, limit: int): return [{"title": "Cached macro", "date": "2026-08-19T08:00:00Z", "source": "CNBC", "scope": "MARKET"}], []
    class Empty(FakeProvider):
        def market_news(self, limit: int): return [], ["CNBC RSS 暂时不可用"]
    service = NewsService(tmp_path, provider=Macro(), now=lambda: NOW)
    assert service.get_market(refresh=True)["source_status"] == "LIVE"
    service.provider = Empty(); service._last_market_refresh_monotonic = float("-inf")
    result = service.get_market(refresh=True)
    assert result["source_status"] == "STALE_CACHE"
    assert result["market_items"][0]["title"] == "Cached macro"


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


def test_market_stream_has_its_own_cache_and_never_becomes_company_items(tmp_path) -> None:
    class MacroProvider(FakeProvider):
        def market_news(self, limit: int):
            return [{"title": "Fed policy update", "date": "2026-08-19T07:30:00Z", "source": "CNBC", "scope": "MARKET"}], []

    provider = MacroProvider([])
    service = NewsService(tmp_path, provider=provider, now=lambda: NOW)
    first = service.get_market(); cached = service.get_market()
    company = service.get("US.AAPL")
    assert first["source_status"] == "LIVE" and cached["source_status"] == "CACHED"
    assert first["market_items"][0]["scope"] == "MARKET"
    assert company["company_items"] == [] and company["market_items"][0]["title"] == "Fed policy update"


def test_manual_micron_query_has_entity_alias_without_expanding_snapshot_universe() -> None:
    assert "micron technology" in entity_terms("MU")
    assert "MU" not in __import__("app.config.news_universe", fromlist=["RESEARCH_UNIVERSE"]).RESEARCH_UNIVERSE


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


def test_news_service_historical_read_never_uses_a_later_snapshot(tmp_path) -> None:
    clock = [NOW]
    provider = FakeProvider([{"title": "AAPL first snapshot", "date": "2026-08-19T07:30:00Z", "source": "TheStreet"}])
    service = NewsService(tmp_path, ttl_seconds=0, provider=provider, now=lambda: clock[0])
    service.get("US.AAPL", refresh=True)
    clock[0] = NOW + timedelta(hours=2)
    provider.rows = [{"title": "AAPL later snapshot", "date": "2026-08-19T09:30:00Z", "source": "TheStreet"}]
    service.get("US.AAPL", refresh=True)

    historical = service.get_at("US.AAPL", (NOW + timedelta(hours=1)).isoformat())
    before_history = service.get_at("US.AAPL", (NOW - timedelta(hours=1)).isoformat())
    assert historical["items"][0]["title"] == "AAPL first snapshot"
    assert before_history["source_status"] == "UNAVAILABLE"


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


def test_news_advice_api_exposes_strict_decision_contract(monkeypatch) -> None:
    import app.api.news as news_api

    class Advice:
        def advice(self, code, *, refresh=False, as_of=None):
            return {"symbol": code, "action": "HOLD", "bias": "BEARISH", "score": -.3, "confidence": .7,
                    "validation_status": "INSUFFICIENT_EVIDENCE", "concise_reason": "样本不足。",
                    "contribution": {"enabled": False, "points": 0, "effect": "NONE"}}

    class Factor:
        def ensure_daily_snapshot(self, *, refresh=False): return {"status": "NOT_DUE"}

    monkeypatch.setattr(news_api, "advice_service", Advice())
    monkeypatch.setattr(news_api, "factor_service", Factor())
    response = TestClient(app).get("/api/news/US.MU/advice")
    assert response.status_code == 200
    assert response.json()["action"] == "HOLD"
    assert response.json()["contribution"]["points"] == 0


def test_news_scorecard_api_is_research_only(monkeypatch) -> None:
    import app.api.news as news_api

    class Scorecard:
        def scorecard(self, code, *, refresh=False, as_of=None):
            return {"schema_version": 1, "research_only": True, "symbol": code, "events": [],
                    "historical_reliability": {"status": "INSUFFICIENT_EVIDENCE"}}

    monkeypatch.setattr(news_api, "scorecard_service", Scorecard())
    response = TestClient(app).get("/api/news/US.MU/scorecard")
    assert response.status_code == 200
    assert response.json()["research_only"] is True
    assert response.json()["events"] == []


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
