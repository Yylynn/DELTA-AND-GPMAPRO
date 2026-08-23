from datetime import datetime, timezone
import json

import pandas as pd

from app.services.news_analysis import NewsAnalyzer
from app.services.news_factor import NewsFactorService
from app.services.news_factor_evaluation import NewsFactorEvaluationService
from app.services.trading_calendar import earliest_trade_at


def test_earliest_trade_is_next_valid_nyse_open_across_holiday_and_dst() -> None:
    assert earliest_trade_at("2026-07-02T20:00:00Z").startswith("2026-07-06T09:30:00-04:00")
    assert earliest_trade_at("2026-11-06T20:00:00Z").startswith("2026-11-09T09:30:00-05:00")


def test_chinese_news_is_not_scored_by_english_finbert() -> None:
    result = NewsAnalyzer().analyze("苹果公司发布新产品")
    assert result["language"] == "ZH"
    assert result["method"] == "UNSUPPORTED_LANGUAGE"
    assert result["model_eligible"] is False


def test_legacy_factor_snapshot_is_quarantined(tmp_path) -> None:
    root = tmp_path / "news_factor_snapshots"; root.mkdir()
    (root / "legacy.json").write_text(json.dumps({"captured_at": "2026-01-01", "responses": [{"symbol": "US.AAPL"}]}), encoding="utf-8")
    service = NewsFactorService(object(), tmp_path / "news_cache")
    assert service._latest() is None


def test_evaluation_reports_missing_aligned_point_in_time_data(tmp_path) -> None:
    snapshots = tmp_path / "snapshots"; prices = tmp_path / "prices"; snapshots.mkdir(); prices.mkdir()
    (snapshots / "valid.json").write_text(json.dumps({"schema_version": 2, "quality_status": "VALID", "captured_at": datetime.now(timezone.utc).isoformat(), "features": {}}), encoding="utf-8")
    result = NewsFactorEvaluationService(snapshots, prices).evaluate()
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["historical_prediction_confidence"] is None
