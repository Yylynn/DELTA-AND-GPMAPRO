"""Read-only, auditable US large-cap DELTA × GPMAPRO screening pool."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import socket
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from app.data.providers import validate_ohlcv
from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmapro_engine import GpmaProEngine
from app.services.trading_calendar import is_session
from app.config.stock_pool_universe import STOCK_POOL_UNIVERSE, STOCK_POOL_UNIVERSE_VERSION
from app.core.config import get_settings

NY = ZoneInfo("America/New_York")
MARKET_CAP_FLOOR_USD, MAX_SNAPSHOT_BATCH, MIN_HISTORY_BARS = 30_000_000_000, 400, 300
PAIR_GAP_TRADING_DAYS, CANDIDATE_TTL_TRADING_DAYS, ROUND_TRIP_COST_BPS = 3, 3, 20
SCHEMA_VERSION, UNIVERSE_VERSION = 2, "US_COMMON_ADR_CAP30B_2026Q3"
BUY_MARKERS = (("b1", "B1"), ("b2", "B2"), ("b3", "B3"), ("bottom_face", "笑脸"), ("bottom_1", "底部箭头 1"), ("bottom_2", "底部箭头 2"), ("bottom_3", "底部箭头 3"))


class StockPoolDataError(RuntimeError):
    pass


class FutuStockPoolDataService:
    """OpenD quote-only adapter; deliberately never imports a trade context."""
    def __init__(self, root: Path, host="127.0.0.1", port=11111, now: Callable[[], datetime] | None = None):
        self.root, self.host, self.port = root, host, port
        self.root.mkdir(parents=True, exist_ok=True)
        self.bars_root = root / "bars"; self.bars_root.mkdir(exist_ok=True)
        self.now = now or (lambda: datetime.now(UTC))

    def connection_status(self) -> dict:
        try:
            with socket.create_connection((self.host, self.port), timeout=.25): reachable, error = True, None
        except OSError as reason: reachable, error = False, str(reason)
        return {"source": "futu_opend", "host": self.host, "port": self.port, "reachable": reachable, "error": error}

    def _ensure_endpoint(self):
        status = self.connection_status()
        if not status["reachable"]: raise StockPoolDataError(f"OpenD unavailable at {self.host}:{self.port}: {status['error']}")

    @staticmethod
    def _chunks(values: list[str], size=MAX_SNAPSHOT_BATCH) -> Iterable[list[str]]:
        for i in range(0, len(values), size): yield values[i:i + size]

    def fetch_universe(self) -> list[dict]:
        self._ensure_endpoint()
        try: from futu import Market, OpenQuoteContext, RET_OK, SecurityType
        except ImportError as error: raise StockPoolDataError("Futu Python SDK is not installed") from error
        context = OpenQuoteContext(host=self.host, port=self.port)
        try:
            ret, frame = context.get_stock_basicinfo(Market.US, SecurityType.STOCK)
            if ret != RET_OK: raise StockPoolDataError(f"OpenD static-list request failed: {frame}")
        finally: context.close()
        result = []
        for row in frame.to_dict("records"):
            code, kind = str(row.get("code", "")).upper(), str(row.get("stock_type", "STOCK")).upper()
            if re.fullmatch(r"US\.[A-Z0-9._-]+", code) and kind in {"", "STOCK", "COMMON", "ADR"}:
                result.append({"code": code, "name": row.get("name") or code[3:], "industry": row.get("industry") or row.get("industry_name") or "未提供", "stock_type": kind or "STOCK"})
        return sorted(result, key=lambda x: x["code"])

    def fetch_market_snapshots(self, codes: list[str]) -> tuple[dict[str, dict], dict[str, int]]:
        self._ensure_endpoint()
        try: from futu import OpenQuoteContext, RET_OK
        except ImportError as error: raise StockPoolDataError("Futu Python SDK is not installed") from error
        output, health = {}, {"batches": 0, "failed_batches": 0}
        for batch in self._chunks(codes):
            health["batches"] += 1; context = OpenQuoteContext(host=self.host, port=self.port)
            try:
                ret, frame = context.get_market_snapshot(batch)
                if ret != RET_OK: health["failed_batches"] += 1; continue
                for row in frame.to_dict("records"):
                    try: price, shares = float(row.get("last_price")), float(row.get("issued_shares"))
                    except (TypeError, ValueError): continue
                    if price > 0 and shares > 0:
                        output[str(row.get("code", "")).upper()] = {"last_price": price, "issued_shares": shares, "market_cap_usd": price * shares, "suspended": bool(row.get("suspension", False)), "currency": "USD"}
            finally: context.close()
        return output, health

    def _bar_path(self, code: str) -> Path: return self.bars_root / f"{code.replace('.', '_')}.csv"
    def load_bars(self, code: str) -> pd.DataFrame:
        frame, _ = validate_ohlcv(pd.read_csv(self._bar_path(code))); return frame

    def sync_daily_bars(self, code: str, min_bars=MIN_HISTORY_BARS) -> tuple[pd.DataFrame | None, str | None]:
        try: existing = self.load_bars(code)
        except (FileNotFoundError, ValueError): existing = None
        start = ((pd.Timestamp(existing.date.max()).date() - timedelta(days=8)).isoformat() if existing is not None and len(existing) >= min_bars else (self.now().date() - timedelta(days=520)).isoformat())
        self._ensure_endpoint()
        try: from futu import AuType, KLType, OpenQuoteContext, RET_OK
        except ImportError as error: return None, "Futu Python SDK is not installed"
        pages, key = [], None; context = OpenQuoteContext(host=self.host, port=self.port)
        try:
            while True:
                ret, page, key = context.request_history_kline(code, start=start, end=self.now().date().isoformat(), ktype=KLType.K_DAY, autype=AuType.QFQ, max_count=1000, page_req_key=key)
                if ret != RET_OK: return None, f"OpenD 日线请求失败：{page}"
                pages.append(page)
                if key is None: break
        except Exception as error: return None, str(error)
        finally: context.close()
        if not pages: return None, "OpenD 未返回日线"
        raw = pd.concat(pages, ignore_index=True)[["time_key", "open", "high", "low", "close", "volume"]].rename(columns={"time_key": "date"})
        try: clean, _ = validate_ohlcv(raw if existing is None else pd.concat([existing, raw], ignore_index=True).drop_duplicates("date", keep="last"))
        except ValueError as error: return None, str(error)
        if len(clean) < min_bars: return None, f"历史日线不足 {min_bars} 根（当前 {len(clean)}）"
        clean.to_csv(self._bar_path(code), index=False); return clean, None


class YahooStockPoolDataService:
    """Zero-key stock-pool data backed by the versioned local US universe."""
    def __init__(self, root: Path, now: Callable[[], datetime] | None = None, ticker_factory=None):
        self.root = root; self.root.mkdir(parents=True, exist_ok=True)
        self.bars_root = root / "bars"; self.bars_root.mkdir(exist_ok=True)
        self.now = now or (lambda: datetime.now(UTC))
        self._ticker_factory = ticker_factory

    def _ticker(self, symbol: str):
        if self._ticker_factory: return self._ticker_factory(symbol)
        try: import yfinance as yf
        except ImportError as error: raise StockPoolDataError("yfinance is not installed") from error
        return yf.Ticker(symbol)

    def connection_status(self) -> dict:
        try:
            import yfinance
            return {"source": "yahoo_finance", "reachable": True, "requires_api_key": False, "version": getattr(yfinance, "__version__", "unknown")}
        except ImportError as error:
            return {"source": "yahoo_finance", "reachable": False, "requires_api_key": False, "error": str(error)}

    def fetch_universe(self) -> list[dict]:
        if not self.connection_status()["reachable"]: raise StockPoolDataError("yfinance is not installed")
        return [{"code": f"US.{symbol}", "name": symbol, "industry": category, "stock_type": "STOCK"} for symbol, category in STOCK_POOL_UNIVERSE.items()]

    @staticmethod
    def _number(container, *keys):
        for key in keys:
            try:
                value = getattr(container, key)
            except (AttributeError, KeyError, TypeError):
                try: value = container.get(key)
                except Exception: value = None
            try:
                number = float(value)
                if pd.notna(number) and number > 0: return number
            except (TypeError, ValueError):
                continue
        return None

    def fetch_market_snapshots(self, codes: list[str]) -> tuple[dict[str, dict], dict[str, int]]:
        output, health = {}, {"batches": 0, "failed_batches": 0}
        for code in codes:
            health["batches"] += 1
            try:
                fast = self._ticker(code.removeprefix("US.")).fast_info
                price = self._number(fast, "last_price", "lastPrice")
                market_cap = self._number(fast, "market_cap", "marketCap")
                shares = self._number(fast, "shares") or (market_cap / price if market_cap and price else None)
                if not (price and shares and market_cap):
                    health["failed_batches"] += 1; continue
                output[code] = {"last_price": price, "issued_shares": shares, "market_cap_usd": market_cap, "suspended": False, "currency": "USD"}
            except Exception:
                health["failed_batches"] += 1
        return output, health

    def _bar_path(self, code: str) -> Path: return self.bars_root / f"{code.replace('.', '_')}.csv"
    def load_bars(self, code: str) -> pd.DataFrame:
        frame, _ = validate_ohlcv(pd.read_csv(self._bar_path(code))); return frame

    def sync_daily_bars(self, code: str, min_bars=MIN_HISTORY_BARS) -> tuple[pd.DataFrame | None, str | None]:
        try: existing = self.load_bars(code)
        except (FileNotFoundError, ValueError): existing = None
        start = ((pd.Timestamp(existing.date.max()).date() - timedelta(days=8)).isoformat() if existing is not None and len(existing) >= min_bars else (self.now().date() - timedelta(days=520)).isoformat())
        end = (self.now().date() + timedelta(days=1)).isoformat()
        try:
            raw = self._ticker(code.removeprefix("US.")).history(start=start, end=end, interval="1d", actions=False, auto_adjust=True, repair=True, timeout=15, raise_errors=True)
            if raw is None or raw.empty: return None, "Yahoo Finance 未返回日线"
            data = raw.reset_index(); date_column = next((x for x in data.columns if str(x).lower() in {"date", "datetime"}), data.columns[0])
            data = data.rename(columns={date_column: "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
            clean, _ = validate_ohlcv(data if existing is None else pd.concat([existing, data], ignore_index=True).drop_duplicates("date", keep="last"))
        except Exception as error: return None, str(error)
        if len(clean) < min_bars: return None, f"历史日线不足 {min_bars} 根（当前 {len(clean)}）"
        clean.to_csv(self._bar_path(code), index=False, float_format="%.10f"); return clean, None


class StockPoolService:
    def __init__(self, root: Path, *, data_service=None, market_alerts=None, news_service=None, now=None):
        self.root = root; self.root.mkdir(parents=True, exist_ok=True)
        settings = get_settings()
        data_root = root.parent / "stock_pool_data"
        self.data = data_service or (FutuStockPoolDataService(data_root) if settings.market_data_provider.lower() == "futu" else YahooStockPoolDataService(data_root / "yahoo"))
        self.market_alerts, self.news_service, self.now = market_alerts, news_service, now or (lambda: datetime.now(timezone.utc))
        self.gpma, self.delta = GpmaProEngine(), ITDDeltaEngine()

    def config(self) -> dict:
        source = self.data.connection_status().get("source")
        return {"market": "US", "provider": source, "universe_version": STOCK_POOL_UNIVERSE_VERSION if source == "yahoo_finance" else UNIVERSE_VERSION, "market_cap_floor_usd": MARKET_CAP_FLOOR_USD, "snapshot_batch_size": MAX_SNAPSHOT_BATCH, "min_daily_bars": MIN_HISTORY_BARS, "pair_gap_trading_days": PAIR_GAP_TRADING_DAYS, "candidate_ttl_trading_days": CANDIDATE_TTL_TRADING_DAYS, "accepted_gpmapro_markers": [x[1] for x in BUY_MARKERS], "round_trip_cost_bps": ROUND_TRIP_COST_BPS, "research_only": True}
    def _path(self, day): return self.root / f"{day}_{UNIVERSE_VERSION}.json"
    @staticmethod
    def _read(path):
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None
    def latest(self):
        for path in sorted(self.root.glob("*.json"), reverse=True):
            item = self._read(path)
            if item and item.get("schema_version") == SCHEMA_VERSION: return item
        return {"status": "NO_SNAPSHOT", "config": self.config(), "message": "尚未生成全市场股票池快照。"}
    def snapshots(self):
        return [{k: item.get(k) for k in ("snapshot_id", "session_date", "scanned_at", "status", "coverage", "market")} for path in sorted(self.root.glob("*.json"), reverse=True) if (item := self._read(path)) and item.get("schema_version") == SCHEMA_VERSION]
    def universe(self):
        latest = self.latest(); return {"config": self.config(), "latest_session": latest.get("session_date"), "universe": latest.get("universe", {}), "health": latest.get("health", self.data.connection_status())}
    def health(self):
        latest = self.latest(); return {"latest_session": latest.get("session_date"), "coverage": latest.get("coverage", {}), "health": latest.get("health", self.data.connection_status()), "status": latest.get("status", "NO_SNAPSHOT")}
    @staticmethod
    def _market_state(snapshot):
        raw = snapshot or {}; regime = str(raw.get("regime", "UNKNOWN")); return {"regime": regime, "risk_score": raw.get("risk_score"), "as_of": raw.get("last_check", {}).get("checked_at"), "is_risk": regime in {"RISK", "CRISIS"}}
    @staticmethod
    def _gap(left, right, dates):
        sessions = pd.DatetimeIndex(pd.to_datetime(dates).dt.normalize().drop_duplicates().sort_values())
        try: return abs(sessions.get_loc(left.normalize()) - sessions.get_loc(right.normalize()))
        except KeyError: return None
    @staticmethod
    def _age(active, dates):
        sessions = pd.DatetimeIndex(pd.to_datetime(dates).dt.normalize().drop_duplicates().sort_values())
        return len(sessions[sessions >= active.normalize()]) - 1

    def _signal_pair(self, bars):
        data = self.gpma.calculate(bars).reset_index(drop=True); analysis = self.delta.analyze(data)
        lows = [pd.Timestamp(x["tradable_on"]).normalize() for x in analysis.get("confirmed_points", []) if x.get("type") == "LOW" and x.get("tradable_on")]
        marker_days = {}
        for _, row in data.iterrows():
            labels = [label for column, label in BUY_MARKERS if bool(row.get(column, False))]
            if labels: marker_days[pd.Timestamp(row.date).normalize()] = labels
        pairs = []
        for low in lows:
            for marker, labels in marker_days.items():
                gap = self._gap(low, marker, data.date)
                if gap is not None and gap <= PAIR_GAP_TRADING_DAYS:
                    active = max(low, marker)
                    if self._age(active, data.date) <= CANDIDATE_TTL_TRADING_DAYS: pairs.append((active, low, marker, gap, labels))
        if not pairs: return None
        active, low, marker, gap, labels = max(pairs, key=lambda x: x[0]); last = data.iloc[-1]
        return {"data_as_of": pd.Timestamp(last.date).date().isoformat(), "delta_low_tradable_on": low.date().isoformat(), "gpmapro": {"date": marker.date().isoformat(), "markers": labels}, "gap_trading_days": int(gap), "active_on": active.date().isoformat(), "signal_available_at": f"{active.date().isoformat()}T16:00:00-05:00", "trend": "BULLISH" if bool(last.get("bull_bg", False)) else "BEARISH" if bool(last.get("bear_bg", False)) else "NEUTRAL", "volume_confirmed": bool(last.get("vol_ok", False))}
    def _news(self, code):
        if not self.news_service: return {"status": "UNAVAILABLE", "veto": False, "reason": "新闻服务未配置。"}
        try:
            insight = self.news_service.insight(code); high_risk = bool(insight.get("high_risk"))
            return {"status": "VETO" if high_risk else "CONFIRM" if insight.get("status") == "READY" else "NEUTRAL", "veto": high_risk, "reason": "检测到负面风险新闻。" if high_risk else "新闻不参与技术入选。", "evidence": insight.get("citations", [])[:3]}
        except Exception as error: return {"status": "UNAVAILABLE", "veto": False, "reason": f"新闻读取失败：{error}"}
    def _candidate(self, meta, snap, bars):
        signal = self._signal_pair(bars)
        if not signal: return None
        return {"symbol": meta["code"], "name": meta.get("name", meta["code"][3:]), "industry": meta.get("industry", "未提供"), "market_cap_usd": snap["market_cap_usd"], "market_cap_inputs": {"last_price": snap["last_price"], "issued_shares": snap["issued_shares"], "currency": "USD"}, **signal, "news": self._news(meta["code"]), "invalidates": "出现最终 GPMAPRO S 信号、趋势或量能转弱、后续日线数据异常，或市场进入 RISK/CRISIS。"}

    def scan(self):
        local = self.now().astimezone(NY); day = local.date().isoformat(); path = self._path(day); existing = self._read(path)
        if existing: return {**existing, "idempotent": True}
        market = self._market_state(self.market_alerts.snapshot() if self.market_alerts else None); health = {"source": self.data.connection_status(), "unscanned": {}, "synchronized": 0}
        try: listed = self.data.fetch_universe(); snapshots, batches = self.data.fetch_market_snapshots([x["code"] for x in listed])
        except StockPoolDataError as error:
            payload = {"schema_version": SCHEMA_VERSION, "snapshot_id": path.stem, "status": "DATA_SOURCE_UNAVAILABLE", "session_date": day, "scanned_at": self.now().astimezone(UTC).isoformat(), "config": self.config(), "market": market, "coverage": {"listed": 0, "cap_eligible": 0, "synchronized": 0, "buy_candidates": 0}, "health": {**health, "unscanned": {"DATA_SOURCE_UNAVAILABLE": 1}, "error": str(error)}, "buy_candidates": [], "market_risk_candidates": [], "universe": {}, "disclaimer": "研究候选，非自动交易或投资建议。"}
            # An unavailable source is health state, not an immutable daily
            # result: leave the date retryable for the five-minute scheduler.
            return {**payload, "idempotent": False}
        eligible, reasons = [], {"MISSING_MARKET_CAP": 0, "BELOW_30B_USD": 0, "SUSPENDED": 0}
        for meta in listed:
            snap = snapshots.get(meta["code"])
            if not snap: reasons["MISSING_MARKET_CAP"] += 1
            elif snap["suspended"]: reasons["SUSPENDED"] += 1
            elif snap["market_cap_usd"] < MARKET_CAP_FLOOR_USD: reasons["BELOW_30B_USD"] += 1
            else: eligible.append((meta, snap))
        technical, failures = [], {}
        for meta, snap in eligible:
            bars, error = self.data.sync_daily_bars(meta["code"])
            if error or bars is None: failures["DAILY_DATA_ERROR"] = failures.get("DAILY_DATA_ERROR", 0) + 1; continue
            health["synchronized"] += 1
            try:
                candidate = self._candidate(meta, snap, bars)
                if candidate: technical.append(candidate)
            except Exception: failures["INDICATOR_ERROR"] = failures.get("INDICATOR_ERROR", 0) + 1
        normal, risk = ([], technical) if market["is_risk"] else (technical, [])
        coverage = {"listed": len(listed), "market_snapshots": len(snapshots), "cap_eligible": len(eligible), "synchronized": health["synchronized"], "buy_candidates": len(normal), "market_risk_candidates": len(risk), "snapshot_batches": batches["batches"], "failed_snapshot_batches": batches["failed_batches"]}
        health["unscanned"] = {k: v for k, v in {**reasons, **failures}.items() if v}
        inputs = [{"code": meta["code"], "name": meta["name"], "market_cap_inputs": snap} for meta, snap in eligible]
        payload = {"schema_version": SCHEMA_VERSION, "snapshot_id": path.stem, "status": "RESEARCH_ONLY", "session_date": day, "scanned_at": self.now().astimezone(UTC).isoformat(), "config": self.config(), "market": market, "coverage": coverage, "health": health, "universe": {"version": STOCK_POOL_UNIVERSE_VERSION if health["source"].get("source") == "yahoo_finance" else UNIVERSE_VERSION, "source": health["source"].get("source", "unknown"), "listed_count": len(listed), "eligible_count": len(eligible), "cap_inputs": inputs}, "buy_candidates": normal, "market_risk_candidates": risk, "disclaimer": "研究候选，非自动交易或投资建议；没有下单、账户或持仓接口。"}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); return {**payload, "idempotent": False}
    def ensure_daily_scan(self):
        local = self.now().astimezone(NY)
        if not is_session(local.date()) or (local.hour, local.minute) < (16, 15): return {"status": "NOT_DUE", "session_date": local.date().isoformat()}
        result = self.scan(); return {"status": "CURRENT" if result.get("idempotent") else "CREATED", **result}
    def evaluation(self):
        rows = []
        for summary in reversed(self.snapshots()):
            payload = self._read(self.root / f"{summary['snapshot_id']}.json")
            if not payload: continue
            for candidate in [*payload.get("buy_candidates", []), *payload.get("market_risk_candidates", [])]:
                try:
                    prices = self.data.load_bars(candidate["symbol"]); prices["date"] = pd.to_datetime(prices.date); prices = prices.sort_values("date").reset_index(drop=True); starts = prices.index[prices.date > pd.Timestamp(candidate["active_on"])].tolist()
                    if not starts: continue
                    for horizon in (5, 10, 20):
                        if starts[0] + horizon - 1 < len(prices): rows.append({"date": candidate["active_on"], "industry": candidate["industry"], "regime": payload.get("market", {}).get("regime", "UNKNOWN"), "horizon": horizon, "net_return": float(prices.close.iloc[starts[0] + horizon - 1] / prices.open.iloc[starts[0]] - 1 - ROUND_TRIP_COST_BPS / 10_000)})
                except (FileNotFoundError, ValueError): continue
        if not rows: return {"status": "INSUFFICIENT_EVIDENCE", "sample_count": 0, "cost_bps": ROUND_TRIP_COST_BPS, "horizons": []}
        frame = pd.DataFrame(rows).sort_values("date"); outcomes = []
        for horizon, part in frame.groupby("horizon"):
            split = max(1, int(len(part) * .6)); oos = part.iloc[split:]
            outcomes.append({"horizon": int(horizon), "sample_count": len(part), "win_rate": round(float((part.net_return > 0).mean()), 4), "mean_net_return": round(float(part.net_return.mean()), 6), "oos_sample_count": len(oos), "oos_mean_net_return": round(float(oos.net_return.mean()), 6) if len(oos) else None, "industry_concentration": round(float(part.industry.value_counts(normalize=True).max()), 4)})
        return {"status": "RESEARCH_ONLY" if len(frame) >= 30 else "INSUFFICIENT_EVIDENCE", "sample_count": len(frame), "cost_bps": ROUND_TRIP_COST_BPS, "method": "chronological_walk_forward; next_US_session_open; fixed_round_trip_cost", "horizons": outcomes, "market_regimes": [{"regime": k, "sample_count": len(x), "mean_net_return": round(float(x.net_return.mean()), 6)} for k, x in frame.groupby("regime")]}
