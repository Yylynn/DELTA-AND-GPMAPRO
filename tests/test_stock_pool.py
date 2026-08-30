from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.services.stock_pool import (
    MARKET_CAP_FLOOR_USD,
    PAIR_GAP_TRADING_DAYS,
    FutuStockPoolDataService,
    StockPoolService,
)


class FakeData:
    def __init__(self, bars): self.bars = bars
    def connection_status(self): return {"reachable": True}
    def fetch_universe(self):
        return [{"code": "US.BIG", "name": "Big", "industry": "Tech"}, {"code": "US.SMALL", "name": "Small", "industry": "Tech"}]
    def fetch_market_snapshots(self, _codes):
        return {"US.BIG": {"last_price": 100, "issued_shares": MARKET_CAP_FLOOR_USD / 100, "market_cap_usd": MARKET_CAP_FLOOR_USD, "suspended": False}, "US.SMALL": {"last_price": 1, "issued_shares": 1, "market_cap_usd": 1, "suspended": False}}, {"batches": 1, "failed_batches": 0}
    def sync_daily_bars(self, code): return (self.bars, None) if code == "US.BIG" else (None, "missing")
    def load_bars(self, _code): return self.bars


def bars():
    dates = pd.bdate_range("2024-01-02", periods=320)
    return pd.DataFrame({"date": dates, "open": range(100, 420), "high": range(101, 421), "low": range(99, 419), "close": range(100, 420), "volume": [1_000_000] * 320})


def test_snapshot_batches_are_limited_to_400():
    chunks = list(FutuStockPoolDataService._chunks([str(i) for i in range(801)]))
    assert [len(chunk) for chunk in chunks] == [400, 400, 1]


def test_pair_gap_uses_trading_sessions_and_merges_same_day_markers(monkeypatch, tmp_path):
    service = StockPoolService(tmp_path, data_service=FakeData(bars()))
    calculated = bars().copy()
    for name in ("b1", "b2", "b3", "bottom_face", "bottom_1", "bottom_2", "bottom_3"): calculated[name] = False
    calculated.loc[319, ["b1", "bottom_2"]] = True
    calculated["bull_bg"], calculated["bear_bg"], calculated["vol_ok"] = True, False, True
    service.gpma.calculate = lambda _bars: calculated
    service.delta.analyze = lambda _data: {"confirmed_points": [{"type": "LOW", "tradable_on": calculated.date.iloc[316].isoformat()}]}
    pair = service._signal_pair(bars())
    assert pair["gap_trading_days"] == PAIR_GAP_TRADING_DAYS
    assert pair["gpmapro"]["markers"] == ["B1", "底部箭头 2"]
    assert pair["active_on"] == calculated.date.iloc[319].date().isoformat()


def test_missing_data_is_health_not_filtered(tmp_path):
    service = StockPoolService(tmp_path, data_service=FakeData(bars()), now=lambda: datetime(2026, 8, 28, tzinfo=timezone.utc))
    service._candidate = lambda *_args: None
    result = service.scan()
    assert "filtered" not in result
    assert result["coverage"]["cap_eligible"] == 1
    assert result["health"]["unscanned"].get("DAILY_DATA_ERROR", 0) == 0


def test_stock_pool_never_imports_trade_context():
    source = Path(__file__).parents[1] / "backend" / "app" / "services" / "stock_pool.py"
    assert "OpenSecTradeContext" not in source.read_text(encoding="utf-8")


def test_independent_api_surface_has_read_only_routes():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    for path in ("/api/stock-pool/latest", "/api/stock-pool/universe", "/api/stock-pool/health", "/api/stock-pool/snapshots", "/api/stock-pool/evaluation"):
        assert client.get(path).status_code == 200
    stock_pool_paths = [getattr(route, "path", "") for route in app.routes]
    assert not any("order" in path or "account" in path or "position" in path for path in stock_pool_paths)
