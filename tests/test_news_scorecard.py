import pandas as pd

from app.services.news_scorecard import NewsImpactScorecardService


def _write_prices(root, symbol, closes, volumes=None):
    volumes = volumes or [100] * len(closes)
    pd.DataFrame({
        "date": pd.date_range("2026-08-24", periods=len(closes), freq="D"),
        "open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes,
    }).to_csv(root / f"{symbol}.csv", index=False)


def test_scorecard_event_reaction_uses_trade_time_and_excess_returns(tmp_path):
    _write_prices(tmp_path, "NVDA", [100, 101, 110, 111, 112, 113, 114], [100] * 5 + [200, 200])
    _write_prices(tmp_path, "SPY", [100, 101, 102, 103, 104, 105, 106])
    _write_prices(tmp_path, "QQQ", [100, 101, 105, 106, 107, 108, 109])
    service = NewsImpactScorecardService(None, None, None, tmp_path)
    event = {"cluster_id": "NVDA:0:e1", "title": "Nvidia raises guidance", "event_type": "GUIDANCE", "direction": .8,
             "high_impact": True, "source_count": 2, "published_at": "2026-08-24T15:00:00Z",
             "earliest_trade_at": "2026-08-25T09:30:00-04:00", "evidence_ids": ["e1"]}
    card = service._event_card(event, {"e1": {"id": "e1", "title": event["title"], "url": "https://example.com/e1", "source_id": "test", "published_at": event["published_at"]}}, "NVDA")
    assert card["reaction"]["status"] == "AVAILABLE"
    assert card["reaction"]["stock_returns"]["1d"] == round(110 / 101 - 1, 4)
    assert card["reaction"]["spy_excess_returns"]["1d"] == round((110 / 101 - 1) - (102 / 101 - 1), 4)
    assert card["reaction"]["sector_excess_returns"]["1d"] == round((110 / 101 - 1) - (105 / 101 - 1), 4)


def test_scorecard_never_interprets_missing_prices_as_neutral(tmp_path):
    service = NewsImpactScorecardService(None, None, None, tmp_path)
    event = {"cluster_id": "AAPL:0:e1", "title": "Apple event", "event_type": "PRODUCT", "direction": .0,
             "high_impact": False, "source_count": 1, "published_at": "2026-08-24T15:00:00Z",
             "earliest_trade_at": "2026-08-25T09:30:00-04:00", "evidence_ids": []}
    card = service._event_card(event, {}, "AAPL")
    assert card["direction"] == "UNKNOWN"
    assert card["reaction"]["status"] == "UNAVAILABLE"
    assert "缺少" in card["reaction"]["message"]
