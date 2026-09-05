from datetime import datetime, timezone
import json

import pandas as pd

from app.services.news_analysis import NewsAnalyzer
from app.services.news_advice import NewsAdviceService, NewsFactorCalculator, apply_news_overlay
from app.services.news_factor import NewsFactorService
from app.services.news_factor_evaluation import NewsFactorEvaluationService
from app.services.trading_calendar import earliest_trade_at


def test_earliest_trade_is_next_valid_nyse_open_across_holiday_and_dst() -> None:
    assert earliest_trade_at("2026-07-02T20:00:00Z").startswith("2026-07-06T09:30:00-04:00")
    assert earliest_trade_at("2026-11-06T20:00:00Z").startswith("2026-11-09T09:30:00-05:00")


def test_chinese_news_degrades_to_topic_only_without_local_model() -> None:
    result = NewsAnalyzer(enable_zh=False).analyze("苹果公司发布新产品")
    assert result["language"] == "ZH"
    assert result["method"] == "ZH_TOPIC_ONLY"
    assert result["event_type"] == "PRODUCT"
    assert result["model_eligible"] is False


def test_chinese_finbert_maps_publisher_labels_and_stays_research_only(monkeypatch) -> None:
    analyzer = NewsAnalyzer()
    monkeypatch.setattr(analyzer, "_zh_finbert", lambda: lambda _: [[
        {"label": "LABEL_0", "score": .05}, {"label": "LABEL_1", "score": .9}, {"label": "LABEL_2", "score": .05},
    ]])
    result = analyzer.analyze("公司业绩大幅增长并上调指引")
    assert result["method"] == "ZH_FINBERT"
    assert result["direction"] == "BULLISH"
    assert result["event_type"] == "EARNINGS"
    assert result["model_eligible"] is False


def test_generic_sec_filing_is_metadata_only_and_neutral() -> None:
    result = NewsAnalyzer().analyze("MU 4 SEC filing", "SEC form 4", "OTHER")
    assert result["method"] == "METADATA_ONLY"
    assert result["direction"] == "NEUTRAL"
    assert result["model_eligible"] is False


def _company_item(source_id: str, *, direction: float = .8, item_id: str = "n1") -> dict:
    return {
        "id": item_id, "title": "Micron raises guidance", "url": f"https://example.com/{item_id}",
        "source": source_id, "source_id": source_id, "publisher": source_id, "scope": "COMPANY",
        "entity_status": "ACCEPTED", "entity_matches": ["mu"], "entity_tickers": ["MU"],
        "published_at": "2026-08-23T20:00:00Z", "available_at": "2026-08-23T20:00:00Z",
        "earliest_trade_at": "2026-08-24T09:30:00-04:00", "factor_eligible": True,
        "allow_summary": True, "summary": "Provider supplied summary",
        "analysis": {"method": "FINBERT", "model_eligible": True, "positive_probability": max(direction, 0),
                     "negative_probability": max(-direction, 0), "neutral_probability": .2,
                     "sentiment_score": direction, "event_type": "GUIDANCE",
                     "direction": "BULLISH" if direction > 0 else "BEARISH", "high_impact": True},
    }


def _response(*items: dict) -> dict:
    return {"symbol": "US.MU", "provider_symbol": "MU", "company_items": list(items), "items": list(items),
            "market_items": [], "source_status": "LIVE", "fetched_at": "2026-08-24T18:00:00Z",
            "is_cached": False, "warning": None}


def test_v3_clusters_syndicated_event_once_and_counts_source_confirmation() -> None:
    result = NewsFactorCalculator().calculate(
        _response(_company_item("openbb_yfinance", item_id="n1"), _company_item("finnhub_company", item_id="n2")),
        "2026-08-24T18:00:00Z",
    )
    assert result["news_count"] == 1
    assert result["data_quality"]["duplicate_count"] == 1
    assert result["events"][0]["source_count"] == 2
    assert result["factor_score"] > 0


def test_v3_time_decay_reduces_the_same_event_contribution() -> None:
    response = _response(_company_item("openbb_yfinance"))
    fresh = NewsFactorCalculator().calculate(response, "2026-08-24T18:00:00Z")
    older = NewsFactorCalculator().calculate(response, "2026-08-27T18:00:00Z")
    assert fresh["components"]["weekly_sentiment"] > older["components"]["weekly_sentiment"] > 0
    assert fresh["factor_score"] > older["factor_score"]


def test_unvalidated_advice_stays_hold_but_exposes_bias_for_symbol_outside_universe(tmp_path) -> None:
    class Evaluation:
        def evaluate(self, **_): return {"status": "INSUFFICIENT_EVIDENCE", "sample_count": 0, "horizons": []}
    class Research:
        def market_regime(self, response): return {"regime": "NEUTRAL", "news_direction": "NEUTRAL"}
    service = NewsAdviceService(None, Evaluation(), Research(), tmp_path)
    result = service.advice("US.MU", as_of="2026-08-24T18:00:00Z", response=_response(_company_item("openbb_yfinance")))
    assert result["symbol"] == "US.MU"
    assert result["action"] == "HOLD"
    assert result["bias"] == "BULLISH"
    assert result["contribution"]["points"] == 0


def test_validated_cross_source_major_event_can_map_to_buy(tmp_path) -> None:
    class Evaluation:
        def evaluate(self, **_): return {"status": "VALIDATED", "sample_count": 200, "horizons": []}
    class Research:
        def market_regime(self, response): return {"regime": "NEUTRAL", "news_direction": "NEUTRAL"}
    service = NewsAdviceService(None, Evaluation(), Research(), tmp_path)
    first = _company_item("openbb_yfinance", item_id="n1"); first["published_at"] = "2026-08-24T17:00:00Z"
    second = _company_item("finnhub_company", item_id="n2"); second["published_at"] = "2026-08-24T17:00:00Z"
    result = service.advice("US.MU", as_of="2026-08-24T18:00:00Z", response=_response(first, second))
    assert result["action"] == "BUY"
    assert 0 < result["contribution"]["points"] <= 5


def test_new_after_hours_event_keeps_the_aggregate_advice_on_hold(tmp_path) -> None:
    class Evaluation:
        def evaluate(self, **_): return {"status": "VALIDATED", "sample_count": 200, "horizons": []}
    class Research:
        def market_regime(self, response): return {"regime": "NEUTRAL", "news_direction": "NEUTRAL"}
    old_one = _company_item("openbb_yfinance", item_id="n1")
    old_two = _company_item("finnhub_company", item_id="n2")
    after_hours = _company_item("sec_edgar", item_id="n3")
    after_hours.update(title="Micron reports strong quarterly earnings", published_at="2026-08-24T17:30:00Z",
                       earliest_trade_at="2026-08-25T09:30:00-04:00")
    after_hours["analysis"]["event_type"] = "EARNINGS"
    service = NewsAdviceService(None, Evaluation(), Research(), tmp_path)
    result = service.advice("US.MU", as_of="2026-08-24T18:00:00Z", response=_response(old_one, old_two, after_hours))
    assert result["earliest_trade_at"] == "2026-08-25T09:30:00-04:00"
    assert result["action"] == "HOLD"
    assert result["contribution"]["points"] == 0


def test_news_overlay_is_capped_and_never_moves_more_than_one_level() -> None:
    negative = {"action": "SELL", "contribution": {"points": -99}}
    result = apply_news_overlay("BUY", 82, negative)
    assert result["action"] == "ACCUMULATE"
    assert result["applied_points"] == -15
    positive = {"action": "BUY", "contribution": {"points": 99}}
    assert apply_news_overlay("HOLD", 30, positive)["action"] == "HOLD"
    assert apply_news_overlay("BUY", 82, positive)["applied_points"] == 5


def test_legacy_factor_snapshot_is_quarantined(tmp_path) -> None:
    root = tmp_path / "news_factor_snapshots"; root.mkdir()
    (root / "legacy.json").write_text(json.dumps({"schema_version": 2, "quality_status": "VALID", "captured_at": "2026-01-01", "responses": [{"symbol": "US.AAPL"}]}), encoding="utf-8")
    service = NewsFactorService(object(), tmp_path / "news_cache")
    assert service._latest() is None


def test_evaluation_reports_missing_aligned_point_in_time_data(tmp_path) -> None:
    snapshots = tmp_path / "snapshots"; prices = tmp_path / "prices"; snapshots.mkdir(); prices.mkdir()
    (snapshots / "valid.json").write_text(json.dumps({"schema_version": 3, "quality_status": "VALID", "session_date": "2026-08-24", "captured_at": datetime.now(timezone.utc).isoformat(), "features": {}}), encoding="utf-8")
    result = NewsFactorEvaluationService(snapshots, prices).evaluate()
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["historical_prediction_confidence"] is None


def test_evaluation_as_of_quarantines_snapshots_captured_after_cutoff(tmp_path) -> None:
    snapshots = tmp_path / "snapshots"; prices = tmp_path / "prices"; snapshots.mkdir(); prices.mkdir()
    for day in ("2026-08-20", "2026-08-25"):
        (snapshots / f"{day}.json").write_text(json.dumps({
            "schema_version": 3, "quality_status": "VALID", "session_date": day,
            "captured_at": f"{day}T20:30:00Z", "features": {},
        }), encoding="utf-8")
    service = NewsFactorEvaluationService(snapshots, prices)
    assert len(service._snapshots("2026-08-24T23:59:00Z")) == 1
    assert service.evaluate("2026-08-24T23:59:00Z")["session_count"] == 1


def test_factor_excludes_articles_published_after_as_of() -> None:
    item = _company_item("openbb_yfinance")
    item["published_at"] = "2026-08-25T20:00:00Z"
    result = NewsFactorCalculator().calculate(_response(item), "2026-08-24T18:00:00Z")
    assert result["factor_score"] == 0
    assert result["events"] == []
    assert result["evidence"][0]["exclusion_reason"] == "发布时间晚于评估时间"
