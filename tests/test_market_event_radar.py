import pandas as pd

from app.services.market_event_radar import MarketEventRadarService
from app.services.news_advice import NewsAdviceService


class News:
    def get_market(self, **_):
        return {"market_items": [
            {"id": "policy", "title": "US bill supports stablecoin framework", "summary": "Treasury liquidity buyback discussed", "source_id": "treasury_press", "source": "U.S. Treasury", "published_at": "2026-08-24T10:00:00Z", "url": "https://example.com/a"},
            {"id": "policy-2", "title": "Stablecoin law and Treasury buyback support risk appetite", "summary": "Bitcoin and crypto equities react", "source_id": "cnbc", "source": "CNBC", "published_at": "2026-08-24T10:05:00Z", "url": "https://example.com/b"},
        ], "fetched_at": "2026-08-24T10:10:00Z", "source_status": "LIVE", "warning": None, "source_health": []}


class Alerts:
    def snapshot(self): return {"active_alerts": []}


def test_radar_clusters_policy_liquidity_and_crypto_transmission(tmp_path):
    radar = MarketEventRadarService(News(), Alerts(), tmp_path)
    result = radar.insight()
    assert result["events"]
    event = result["events"][0]
    assert {theme["id"] for theme in event["themes"]} >= {"POLICY_REGULATION", "LIQUIDITY_TREASURY", "CRYPTO_POLICY"}
    assets = {row["asset"] for row in event["transmission"]}
    assert {"XLF", "JPM", "IBIT", "COIN"} <= assets
    assert "SPY" not in assets and "QQQ" not in assets
    assert next(row for row in event["transmission"] if row["asset"] == "COIN")["kind"] == "STOCK"
    assert event["confirmation"] == "CONFIRMED"
    assert "官方发布" in event["confirmation_reason"]
    assert event["headline"]["kind"] == "官方发布"
    assert {"金融", "加密"} <= set(event["industries"])
    assert "事实层" in event["interpretation"]["basis"]
    assert result["headline_event_map"]["policy"] == event["event_id"]
    assert result["headline_event_map"]["policy-2"] == event["event_id"]
    assert (tmp_path / "market_event_snapshots").exists()


def test_radar_pending_confirmation_requires_close_time_and_independent_sources(tmp_path):
    radar = MarketEventRadarService(News(), Alerts(), tmp_path)
    item = {"id": "one", "title": "AI semiconductor demand rises", "source_id": "cnbc", "source": "CNBC", "published_at": "2026-08-24T10:00:00Z", "url": "https://example.com/one"}
    distant = {**item, "id": "two", "source_id": "marketwatch", "source": "MarketWatch", "published_at": "2026-08-26T10:01:00Z", "url": "https://example.com/two"}
    events = radar._clusters([item, distant])
    assert len(events) == 2
    assert events[0]["confirmation"] == "PENDING"
    assert "不需要人工操作" in events[0]["confirmation_reason"]


def test_reaction_uses_next_session_and_sector_excess_return(tmp_path):
    radar = MarketEventRadarService(News(), Alerts(), tmp_path)
    dates = pd.date_range("2026-08-24", periods=8, freq="D")
    def frame(closes): return pd.DataFrame({"date": dates, "close": closes})
    event = {"published_at": "2026-08-24T12:00:00Z", "transmission": [{"asset": "NVDA", "sector": "半导体", "direction": "BULLISH", "basis": "test", "kind": "STOCK"}]}
    result = radar._reaction(event, {"NVDA": frame([100, 101, 110, 111, 112, 113, 114, 115]), "SOXX": frame([100, 101, 105, 106, 107, 108, 109, 110]), "SPY": frame([100] * 8)})
    item = result["items"][0]
    assert result["status"] == "AVAILABLE"
    assert item["benchmark"] == "SOXX"
    assert item["returns"]["1d"] == round(110 / 101 - 1, 4)
    assert item["excess_returns"]["1d"] == round((110 / 101 - 1) - (105 / 101 - 1), 4)


def test_retail_headline_does_not_match_ai_substring_and_gets_fact_summary(tmp_path):
    radar = MarketEventRadarService(News(), Alerts(), tmp_path)
    item = {"id": "dks", "title": "Dick's Sporting Goods stock falls 30% as retailer misses expectations, cites 'challenging' footwear market", "source_id": "cnbc", "source": "CNBC", "published_at": "2026-08-26T04:38:59+08:00", "url": "https://example.com/dks"}
    event = radar._clusters([item])[0]
    assert {theme["id"] for theme in event["themes"]} == {"RETAIL_CONSUMER"}
    assert {row["asset"] for row in event["transmission"]} >= {"XRT", "DKS", "NKE"}
    assert "业绩未达市场预期" in event["interpretation"]["fact_summary"]
    assert "DKS" in event["interpretation"]["conclusion"]
    assert event["industries"] == ["消费"]


def test_industry_fallback_and_response_counts_are_auditable(tmp_path):
    radar = MarketEventRadarService(News(), Alerts(), tmp_path)
    assert radar._industries([]) == ["宏观综合"]
    result = radar.insight()
    assert result["industry_counts"]["金融"] == 1
    assert result["industry_counts"]["加密"] == 1


def test_radar_response_is_capped_at_thirty_events(tmp_path):
    class ManyNews:
        def get_market(self, **_):
            dates = pd.date_range("2026-01-01", periods=35, freq="26h")
            return {"market_items": [
                {"id": f"tech-{index}", "title": f"AI semiconductor demand update {index}", "source_id": "cnbc", "source": "CNBC", "published_at": stamp.isoformat(), "url": f"https://example.com/{index}"}
                for index, stamp in enumerate(dates)
            ], "fetched_at": dates[-1].isoformat(), "source_status": "LIVE", "warning": None, "source_health": []}

    radar = MarketEventRadarService(ManyNews(), Alerts(), tmp_path)
    radar._market_frames = lambda _: {}
    result = radar.insight()
    assert len(result["events"]) == 30
    assert result["industry_counts"]["科技"] == 30


def test_research_guidance_never_changes_strict_action(tmp_path):
    class Evaluation:
        def evaluate(self, **_): return {"status": "INSUFFICIENT_EVIDENCE", "sample_count": 0, "horizons": []}
    class Research:
        def market_regime(self, _): return {"regime": "NEUTRAL", "news_direction": "NEUTRAL"}
    response = {"symbol": "US.AAPL", "source_status": "LIVE", "fetched_at": "2026-08-24T10:00:00Z", "company_items": [{"id": "a", "title": "Apple raises guidance", "source_id": "openbb_yfinance", "published_at": "2026-08-24T09:00:00Z", "available_at": "2026-08-24T09:00:00Z", "entity_status": "ACCEPTED", "factor_eligible": False, "scope": "COMPANY", "analysis": {"method": "RULE_FALLBACK", "model_eligible": False, "sentiment_score": .6, "event_type": "GUIDANCE", "high_impact": True}}], "market_items": []}
    result = NewsAdviceService(None, Evaluation(), Research(), tmp_path).advice("US.AAPL", as_of="2026-08-24T18:00:00Z", response=response)
    assert result["action"] == "HOLD"
    assert result["research_guidance"]["bias"] == "BULLISH"
    assert result["contribution"]["points"] == 0
