"""Daily, read-only market-volatility alerts using Yahoo Finance public data."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.services.gpmapro_engine import GpmaProEngine
from app.core.config import get_settings

NEW_YORK = ZoneInfo("America/New_York")
CACHE_SECONDS = 300
TECHNICAL_LOOKBACK_SESSIONS = 3
RISK_HISTORY_LIMIT = 500
STALE_CACHE_SECONDS = 60 * 60 * 24 * 7
MAX_PROVIDER_WORKERS = 4
CBOE_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
DEFAULT_INDICATORS = [
    {"id": "vix", "label": "VIX", "code": "^VIX", "watch_level": 20.0, "risk_level": 25.0},
    {"id": "vxn", "label": "VXN", "code": "^VXN", "watch_level": 25.0, "risk_level": 30.0},
    {"id": "vvix", "label": "VVIX", "code": "^VVIX", "watch_level": None, "risk_level": None},
    {"id": "vixy", "label": "VIXY", "code": "VIXY", "watch_level": None, "risk_level": None},
]
MARKET_INDEX_TECHNICAL_INDICATORS = [
    {"id": "sp500", "label": "标普 500", "code": "^GSPC", "provider_symbol": "SPY", "asset_type": "MARKET_INDEX"},
    {"id": "nasdaq100", "label": "纳斯达克 100", "code": "^NDX", "provider_symbol": "QQQ", "asset_type": "MARKET_INDEX"},
    {"id": "nasdaq_composite", "label": "纳斯达克综合指数", "code": "^IXIC", "provider_symbol": "QQQ", "asset_type": "MARKET_INDEX"},
]
# These liquid public proxies deliberately keep v1 provider-neutral.  The
# service already accepts an injected fetcher, so adding a FRED/commercial
# adapter later does not alter the scoring or API contract.
RISK_MODULE_INDICATORS = [
    {"id": "tlt", "label": "长期美债", "code": "TLT", "provider_symbol": "TLT", "module": "RATES"},
    {"id": "tnx", "label": "10 年美债收益率", "code": "^TNX", "fred_series": "DGS10", "module": "RATES"},
    {"id": "hyg", "label": "高收益债", "code": "HYG", "provider_symbol": "HYG", "module": "CREDIT_LIQUIDITY"},
    {"id": "lqd", "label": "投资级债", "code": "LQD", "provider_symbol": "LQD", "module": "CREDIT_LIQUIDITY"},
    {"id": "hy_oas", "label": "高收益信用利差", "code": "BAMLH0A0HYM2", "fred_series": "BAMLH0A0HYM2", "module": "CREDIT_LIQUIDITY"},
    {"id": "ig_oas", "label": "投资级信用利差", "code": "BAMLC0A0CM", "fred_series": "BAMLC0A0CM", "module": "CREDIT_LIQUIDITY"},
    {"id": "uup", "label": "美元", "code": "UUP", "provider_symbol": "UUP", "module": "CREDIT_LIQUIDITY"},
    {"id": "oil", "label": "WTI 原油", "code": "CL=F", "provider_symbol": "WTI/USD", "module": "GLOBAL"},
    {"id": "gold", "label": "黄金", "code": "GC=F", "provider_symbol": "XAU/USD", "module": "GLOBAL"},
    {"id": "yen", "label": "日元", "code": "JPY=X", "provider_symbol": "USD/JPY", "module": "GLOBAL"},
    {"id": "bitcoin", "label": "比特币", "code": "BTC-USD", "provider_symbol": "BTC/USD", "module": "GLOBAL"},
]
RISK_MODULE_LABELS = {
    "VOLATILITY": "波动率", "EQUITY": "权益压力", "RATES": "利率压力",
    "CREDIT_LIQUIDITY": "信用与流动性", "GLOBAL": "全球风险传导",
}
TECHNICAL_SIGNALS = [
    ("b1", "B1", "BULLISH", "上行技术信号"),
    ("b2", "B2", "BULLISH", "上行技术信号"),
    ("b3", "B3", "BULLISH", "上行技术信号"),
    ("s1", "S1", "BEARISH", "下行技术信号"),
    ("s2", "S2", "BEARISH", "下行技术信号"),
    ("top_face", "顶部笑脸", "TOP_DIVERGENCE", "顶部背离"),
    ("bottom_face", "底部笑脸", "BOTTOM_DIVERGENCE", "底部背离"),
    ("top_2", "顶部二级箭头", "TOP_DIVERGENCE", "顶部背离"),
    ("bottom_2", "底部二级箭头", "BOTTOM_DIVERGENCE", "底部背离"),
    ("top_3", "顶部三级箭头", "TOP_DIVERGENCE", "顶部背离"),
    ("bottom_3", "底部三级箭头", "BOTTOM_DIVERGENCE", "底部背离"),
]


class MarketVolatilityAlertService:
    """Persists public observations, a five-minute cache and daily alerts."""

    def __init__(self, root: Path | None = None, fetcher: Callable[[str], pd.DataFrame] | None = None, fetch_timeout_seconds: float = 8.0, now: Callable[[], datetime] | None = None):
        self.root = root or Path(__file__).resolve().parents[3] / "data" / "market_volatility_alerts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.json"
        self.fetcher = fetcher
        self.fetch_timeout_seconds, self.now = fetch_timeout_seconds, now or (lambda: datetime.now(UTC))

    @property
    def _settings(self):
        return get_settings()

    def _provider_health(self) -> dict:
        settings = self._settings
        return {
            "CBOE": {"status": "AVAILABLE", "configured": True},
            "TWELVE_DATA": {"status": "AVAILABLE" if settings.twelve_data_api_key else "NOT_CONFIGURED", "configured": bool(settings.twelve_data_api_key)},
            "FRED_API": {"status": "AVAILABLE" if settings.fred_api_key else "NOT_CONFIGURED", "configured": bool(settings.fred_api_key)},
            "FRED_CSV": {"status": "FALLBACK", "configured": True},
            "YAHOO_FINANCE": {"status": "FALLBACK", "configured": True},
        }

    def check_providers(self) -> dict:
        """Read-only connectivity check.  Keys are never returned or persisted."""
        providers = self._provider_health()
        probes = {
            "CBOE": lambda: self._fetch_cboe_daily_bars("VIX"),
            "TWELVE_DATA": lambda: self._fetch_twelve_daily_bars("SPY"),
            "FRED_CSV": lambda: self._fetch_fred_csv_daily_bars("DGS10"),
        }
        for provider, probe in probes.items():
            if providers[provider]["status"] == "NOT_CONFIGURED": continue
            try:
                frame = self._completed_bars(probe())
                providers[provider].update(status="OK", as_of=str(frame.iloc[-1].date))
            except Exception as error: providers[provider].update(status="FAILED", error=str(error))
        return {"providers": providers, "checked_at": self.now().isoformat()}

    def _get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        """Small bounded retry budget; the scan supplies its own concurrency cap."""
        error: Exception | None = None
        for attempt in range(2):
            try:
                response = httpx.get(url, params=params, timeout=self.fetch_timeout_seconds, headers={"User-Agent": "DELTA-Time-Space/1.0"})
                if response.status_code != 429 and response.status_code < 500: return response
                error = RuntimeError(f"HTTP {response.status_code}")
            except httpx.HTTPError as exc: error = exc
            if attempt == 0:
                import time as retry_time
                retry_time.sleep(.25)
        raise RuntimeError(f"request failed after retry: {error}")

    @staticmethod
    def _frame(rows: list[dict]) -> pd.DataFrame:
        frame = pd.DataFrame(rows)
        if frame.empty or "close" not in frame: raise RuntimeError("provider returned no daily bars")
        for column in ("open", "high", "low", "close", "volume"):
            if column not in frame: frame[column] = None
        return frame[["date", "open", "high", "low", "close", "volume"]]

    def _fetch_cboe_daily_bars(self, symbol: str) -> pd.DataFrame:
        response = self._get(CBOE_HISTORY_URL.format(symbol=symbol));
        if response.status_code >= 400: raise RuntimeError(f"Cboe request failed (HTTP {response.status_code})")
        raw = pd.read_csv(__import__("io").StringIO(response.text))
        columns = {str(column).strip().upper(): column for column in raw.columns}
        date_column, close_column = columns.get("DATE"), columns.get("CLOSE") or columns.get(symbol.upper())
        if not date_column or not close_column: raise RuntimeError("Cboe returned an unexpected historical-data format")
        return self._frame([{"date": value[date_column], "close": value[close_column]} for _, value in raw.iterrows() if pd.notna(value[close_column])])

    def _fetch_twelve_daily_bars(self, symbol: str) -> pd.DataFrame:
        key = self._settings.twelve_data_api_key
        if not key: raise RuntimeError("Twelve Data is not configured")
        response = self._get("https://api.twelvedata.com/time_series", params={"symbol": symbol, "interval": "1day", "outputsize": 5000, "apikey": key})
        payload = response.json()
        if response.status_code >= 400 or payload.get("status") == "error": raise RuntimeError(f"Twelve Data: {payload.get('message', response.status_code)}")
        values = payload.get("values") or []
        return self._frame([{"date": value.get("datetime"), "open": value.get("open"), "high": value.get("high"), "low": value.get("low"), "close": value.get("close"), "volume": value.get("volume")} for value in values])

    def _fetch_fred_api_daily_bars(self, series: str) -> pd.DataFrame:
        key = self._settings.fred_api_key
        if not key: raise RuntimeError("FRED is not configured")
        response = self._get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": series, "api_key": key, "file_type": "json", "observation_start": "2000-01-01", "sort_order": "asc"})
        payload = response.json()
        if response.status_code >= 400 or payload.get("error_code"): raise RuntimeError(f"FRED: {payload.get('error_message', response.status_code)}")
        return self._frame([{"date": value["date"], "close": value["value"]} for value in payload.get("observations", []) if value.get("value") not in (None, ".")])

    def _fetch_fred_csv_daily_bars(self, series: str) -> pd.DataFrame:
        """Official FRED graph export; available without a personal API key."""
        response = self._get(FRED_GRAPH_URL.format(series=quote(series, safe="")))
        if response.status_code >= 400: raise RuntimeError(f"FRED CSV request failed (HTTP {response.status_code})")
        raw = pd.read_csv(__import__("io").StringIO(response.text))
        columns = {str(column).strip().upper(): column for column in raw.columns}
        date_column, value_column = columns.get("OBSERVATION_DATE"), columns.get(series.upper())
        if not date_column or not value_column: raise RuntimeError("FRED CSV returned an unexpected historical-data format")
        return self._frame([{"date": row[date_column], "close": row[value_column]} for _, row in raw.iterrows() if pd.notna(row[value_column]) and str(row[value_column]) != "."])

    def _fetch_indicator(self, indicator: dict) -> tuple[pd.DataFrame, str]:
        """Return the preferred provider's bars, falling back only on real failure."""
        if self.fetcher:
            return self.fetcher(indicator["code"]), "TEST"
        attempts: list[tuple[str, Callable[[], pd.DataFrame]]] = []
        if indicator.get("id") in {"vix", "vxn", "vvix"}:
            attempts.append(("CBOE", lambda: self._fetch_cboe_daily_bars(indicator["id"].upper())))
        if indicator.get("fred_series"):
            if self._settings.fred_api_key:
                attempts.append(("FRED_API", lambda: self._fetch_fred_api_daily_bars(indicator["fred_series"])))
            attempts.append(("FRED_CSV", lambda: self._fetch_fred_csv_daily_bars(indicator["fred_series"])))
        if indicator.get("provider_symbol") or indicator.get("id") == "vixy":
            attempts.append(("TWELVE_DATA", lambda: self._fetch_twelve_daily_bars(indicator.get("provider_symbol", indicator["code"]))))
        attempts.append(("YAHOO_FINANCE", lambda: self._fetch_yahoo_daily_bars(indicator["code"])))
        failures = []
        for provider, call in attempts:
            try: return call(), provider
            except Exception as error: failures.append(f"{provider}: {error}")
        raise RuntimeError("; ".join(failures))

    @staticmethod
    def _default_state() -> dict:
        return {"config": {"provider": "YAHOO_FINANCE", "change_threshold_pct": 3.0, "indicators": DEFAULT_INDICATORS}, "market_cache": {}, "observations": [], "market_index_observations": [], "alerts": [], "risk_history": [], "risk_state": None, "last_check": None}

    def _state(self) -> dict:
        if not self.path.exists(): return self._default_state()
        try: state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return self._default_state()
        legacy = state.get("config", {}).get("provider") != "YAHOO_FINANCE" or any(item.get("id") == "vxmain" for item in state.get("config", {}).get("indicators", []))
        if legacy:
            threshold = state.get("config", {}).get("change_threshold_pct", 3.0)
            state["config"] = {"provider": "YAHOO_FINANCE", "change_threshold_pct": threshold, "indicators": DEFAULT_INDICATORS}; state["market_cache"] = {}
        state.setdefault("market_cache", {}); state.setdefault("observations", []); state.setdefault("market_index_observations", []); state.setdefault("alerts", []); state.setdefault("risk_history", []); state.setdefault("risk_state", None); state.setdefault("last_check", None)
        return state

    def _save(self, state: dict) -> None:
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def snapshot(self) -> dict:
        state = self._state()
        alerts = state["alerts"][-50:]
        sessions = sorted({str(row["date"]) for entry in state["market_cache"].values() for row in entry.get("bars", []) if row.get("date")})[-TECHNICAL_LOOKBACK_SESSIONS:]
        cutoff = sessions[0] if sessions else None
        technical = [item for item in alerts if item.get("category") == "GPMAPRO_TECHNICAL" and (cutoff is None or item.get("signal_date", item["date"]) >= cutoff)]
        volatility_technical = [item for item in technical if item.get("asset_type", "VOLATILITY") == "VOLATILITY"]
        market_index_technical = [item for item in technical if item.get("asset_type") == "MARKET_INDEX"]
        # A daily-change/level alert belongs to one completed close only.  Keep
        # it in history, but never let an unread alert from a prior session
        # remain in the live banner after a later observation supersedes it.
        latest_observations = {item["id"]: item for item in state["observations"] if item.get("id") and item.get("date")}
        current_volatility_alerts = [
            item for item in alerts
            if item.get("category") != "GPMAPRO_TECHNICAL"
            and (latest := latest_observations.get(item.get("indicator_id"))) is not None
            and item.get("date") == latest["date"]
        ]
        active_alerts = current_volatility_alerts + technical
        index_latest = {item["id"]: item for item in state["market_index_observations"]}
        risk_state = state.get("risk_state") or {}
        health = risk_state.get("data_health", {"status": "DATA_PENDING", "available_modules": 0, "total_modules": len(RISK_MODULE_LABELS), "failures": [], "sources": [], "core_checks": {}, "missing_core": list(RISK_MODULE_LABELS.values()), "indicator_sources": []})
        health.setdefault("providers", self._provider_health())
        # States saved before explainable completeness gating have no evidence
        # needed to uphold a confirmed regime.  Keep their historical score for
        # audit, but require one fresh scan before presenting a conclusion.
        if "core_checks" not in health:
            health = {**health, "status": "DATA_PENDING", "core_checks": {}, "missing_core": ["需刷新以核验关键模块"], "indicator_sources": []}
        display_regime = "DATA_PENDING" if health.get("status") == "DATA_PENDING" else risk_state.get("display_regime", risk_state.get("regime", "DATA_PENDING"))
        return {"config": state["config"], "observations": state["observations"][-20:], "alerts": alerts, "active_alerts": active_alerts, "technical_signals": volatility_technical, "market_index_technical_signals": market_index_technical, "market_index_technical_indicators": MARKET_INDEX_TECHNICAL_INDICATORS, "market_index_last_check": list(index_latest.values()), "technical_lookback_sessions": TECHNICAL_LOOKBACK_SESSIONS, "risk_score": risk_state.get("risk_score", 0), "regime": display_regime, "raw_regime": risk_state.get("raw_regime", risk_state.get("regime", "NORMAL")), "display_regime": display_regime, "modules": risk_state.get("modules", []), "evidence": risk_state.get("evidence", []), "methodology": risk_state.get("methodology", self._methodology()), "data_health": health, "risk_history": state.get("risk_history", [])[-20:], "risk_transition": risk_state.get("transition", "等待首次检查"), "last_check": state["last_check"]}

    def _fetch_yahoo_daily_bars(self, symbol: str) -> pd.DataFrame:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        try:
            response = self._get(url, params={"range": "2y", "interval": "1d", "includePrePost": "false", "events": "history"})
        except httpx.HTTPError as error: raise RuntimeError(f"Yahoo Finance network error: {error}") from error
        if response.status_code == 429: raise RuntimeError("Yahoo Finance rate limit (HTTP 429); retry after five minutes")
        if response.status_code >= 400: raise RuntimeError(f"Yahoo Finance request failed (HTTP {response.status_code})")
        payload = response.json().get("chart", {})
        if payload.get("error"): raise RuntimeError(f"Yahoo Finance: {payload['error'].get('description', payload['error'])}")
        result = (payload.get("result") or [None])[0]
        if not result: raise RuntimeError("Yahoo Finance returned no market data")
        quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
        def value_at(name: str, index: int):
            values = quote_data.get(name) or []
            return values[index] if index < len(values) else None
        rows = []
        for index, timestamp in enumerate(result.get("timestamp") or []):
            close = value_at("close", index)
            if close is None: continue
            rows.append({"date": datetime.fromtimestamp(timestamp, UTC).astimezone(NEW_YORK).date().isoformat(), "open": value_at("open", index), "high": value_at("high", index), "low": value_at("low", index), "close": close, "volume": value_at("volume", index)})
        if not rows: raise RuntimeError("Yahoo Finance returned no daily closing prices")
        return pd.DataFrame(rows)

    def _completed_bars(self, frame: pd.DataFrame) -> pd.DataFrame:
        data = frame.copy(); data["date"] = pd.to_datetime(data["date"]).dt.date
        for column in ("open", "high", "low", "close", "volume"):
            if column in data: data[column] = pd.to_numeric(data[column], errors="coerce")
        data = data.dropna(subset=["close"]).sort_values("date")
        now_ny = self.now().astimezone(NEW_YORK)
        if now_ny.time() < time(16, 15): data = data[data["date"] < now_ny.date()]
        if len(data) < 2: raise ValueError("at least two completed daily closes are required")
        data["date"] = data["date"].astype(str)
        return data

    def _fetch_one_with_timeout(self, code: str) -> pd.DataFrame:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-alert-validate")
        future = executor.submit(self._fetch_yahoo_daily_bars, code); completed, _ = wait([future], timeout=self.fetch_timeout_seconds); executor.shutdown(wait=False, cancel_futures=True)
        if not completed: future.cancel(); raise TimeoutError(f"Yahoo Finance request timed out after {self.fetch_timeout_seconds:g}s")
        return self._completed_bars(future.result())

    def update_config(self, payload: dict) -> dict:
        indicators = payload.get("indicators", [])
        if {item.get("id") for item in indicators} != {item["id"] for item in DEFAULT_INDICATORS}: raise ValueError("indicators must contain vix, vxn, vvix and vixy exactly once")
        cleaned = []
        for item in indicators:
            code = str(item.get("code", "")).strip().upper()
            if not code: raise ValueError(f"invalid Yahoo Finance code for {item.get('id')}")
            base = next(entry for entry in DEFAULT_INDICATORS if entry["id"] == item["id"]); cleaned.append({**base, "code": code})
        threshold = float(payload.get("change_threshold_pct", 3.0))
        if threshold <= 0 or threshold > 100: raise ValueError("change_threshold_pct must be between 0 and 100")
        state, cache = self._state(), {}
        for item in cleaned:
            try:
                bars, provider = self._fetch_indicator(item)
                cache[item["id"]] = {"code": item["code"], "provider": provider, "fetched_at": self.now().isoformat(), "bars": self._completed_bars(bars).to_dict(orient="records")}
            except Exception as error: raise ValueError(f"unable to validate {item['label']} ({item['code']}): {error}") from error
        state["config"] = {"provider": "YAHOO_FINANCE", "change_threshold_pct": threshold, "indicators": cleaned}; state["market_cache"] = cache; self._save(state)
        return self.snapshot()

    def _cached_bars(self, state: dict, indicator: dict) -> pd.DataFrame | None:
        entry = state["market_cache"].get(indicator["id"])
        if not entry or entry.get("code") != indicator["code"]: return None
        try: age = (self.now() - datetime.fromisoformat(entry["fetched_at"])).total_seconds()
        except (TypeError, ValueError): return None
        return self._completed_bars(pd.DataFrame(entry["bars"])) if age < CACHE_SECONDS else None

    def _stale_cached_bars(self, state: dict, indicator: dict) -> tuple[pd.DataFrame, float] | None:
        entry = state["market_cache"].get(indicator["id"])
        if not entry or entry.get("code") != indicator["code"]: return None
        try: age = (self.now() - datetime.fromisoformat(entry["fetched_at"])).total_seconds()
        except (TypeError, ValueError): return None
        if age > STALE_CACHE_SECONDS: return None
        try: return self._completed_bars(pd.DataFrame(entry["bars"])), age
        except Exception: return None

    @staticmethod
    def _severity(reasons: list[dict]) -> str:
        return "RISK" if any(reason["severity"] == "RISK" for reason in reasons) else "WATCH" if reasons else "NORMAL"

    def _technical_events(self, indicator: dict, frame: pd.DataFrame) -> list[dict]:
        required = ["date", "open", "high", "low", "close", "volume"]
        if not set(required).issubset(frame.columns): return []
        source = frame.dropna(subset=required).copy()
        if len(source) < 60: return []
        calculated = GpmaProEngine().calculate(source)
        events: list[dict] = []
        asset_type = indicator.get("asset_type", "VOLATILITY")
        asset_label = "指数" if asset_type == "MARKET_INDEX" else "波动率"
        # A three-session catch-up window makes brief offline periods visible,
        # while the event key below prevents the same historical marker from
        # being sent more than once.
        for _, row in calculated.tail(TECHNICAL_LOOKBACK_SESSIONS).iterrows():
            for column, code, direction, description in TECHNICAL_SIGNALS:
                if bool(row[column]):
                    signal_date = row.date.date().isoformat()
                    message = f"{asset_label}{description}"
                    events.append({"category": "GPMAPRO_TECHNICAL", "asset_type": asset_type, "indicator_id": indicator["id"], "label": indicator["label"], "code": indicator["code"], "date": signal_date, "signal_date": signal_date, "signal_code": code, "signal_direction": direction, "display_label": f"{code} · {message}", "severity": "WATCH", "message": f"{code}：{message}"})
        return events

    @staticmethod
    def _percentile(values: pd.Series, value: float) -> float | None:
        """Trailing percentile, calculated only from information available now."""
        clean = values.dropna().tail(252)
        if len(clean) < 20: return None
        return round(float((clean <= value).mean() * 100), 1)

    @staticmethod
    def _last(frame: pd.DataFrame, days: int = 1) -> float | None:
        if len(frame) <= days: return None
        prior, current = float(frame.iloc[-days - 1].close), float(frame.iloc[-1].close)
        return None if prior == 0 else (current / prior - 1) * 100

    def _frame_metric(self, frame: pd.DataFrame, *, direction: int = 1) -> dict:
        closes = frame["close"].astype(float)
        current = float(closes.iloc[-1]); change_5d = self._last(frame, 5)
        percentile = self._percentile(closes, current) if direction > 0 else self._percentile(-closes, -current)
        return {"close": round(current, 4), "percentile": percentile, "change_5d": None if change_5d is None else round(change_5d, 3), "trend": "UP" if len(closes) >= 20 and current >= float(closes.tail(20).mean()) else "DOWN"}

    @staticmethod
    def _methodology() -> dict:
        return {
            "version": "market-risk-v2-explainable",
            "history_sessions": 252,
            "change_sessions": 5,
            "trend_sessions": 20,
            "aggregation": "每个模块只取压力最高的一项证据；综合分为可用模块的等权平均。",
            "regime_rules": [
                "任一模块得分 ≥ 90：危机",
                "至少两个模块得分 ≥ 60 且综合分 ≥ 60：高风险",
                "综合分 ≥ 35 或存在压力模块：重点观察",
                "其余：正常",
            ],
            "data_gate": "波动率、权益、利率和信用模块须有新鲜核心证据；信用模块还须至少一条官方 OAS 信用利差。否则状态为数据待确认。",
        }

    def _risk_snapshot(self, frames: dict[str, pd.DataFrame], sources: dict[str, str], failures: list[dict], checked_at: str) -> dict:
        """Transparent, module-capped risk score.  Correlated volatility inputs
        contribute through their maximum stress, not their sum."""
        modules: list[dict] = []
        evidence: list[dict] = []

        def add_module(key: str, items: list[tuple[str, int]], scorer):
            available = [(identifier, frames[identifier], direction) for identifier, direction in items if identifier in frames]
            if not available:
                modules.append({"id": key, "label": RISK_MODULE_LABELS[key], "score": None, "weight": 0, "status": "UNAVAILABLE", "evidence": []})
                return
            result = scorer(available)
            module_evidence = result.pop("evidence")
            for item in module_evidence:
                identifier = item.get("indicator_id")
                source = sources.get(identifier, "UNKNOWN")
                item["source"] = source
                if identifier in frames:
                    item["as_of"] = str(frames[identifier].iloc[-1].date)
            weight = 1
            modules.append({"id": key, "label": RISK_MODULE_LABELS[key], "weight": weight, "status": "AVAILABLE", **result, "evidence": module_evidence})
            evidence.extend(module_evidence)

        def volatility(available):
            items = []
            config_by_id = {item["id"]: item for item in self._state()["config"]["indicators"]}
            for identifier, frame, _ in available:
                metric = self._frame_metric(frame)
                config = config_by_id.get(identifier, {})
                absolute = 100 if config.get("risk_level") is not None and metric["close"] >= config["risk_level"] else 70 if config.get("watch_level") is not None and metric["close"] >= config["watch_level"] else 0
                adaptive = metric["percentile"] or 0
                impulse = min(100, max(0, (metric["change_5d"] or 0) * 12))
                score = round(max(absolute, adaptive, impulse))
                items.append((score, identifier, metric, absolute, adaptive, impulse))
            score, identifier, metric, absolute, adaptive, impulse = max(items, key=lambda item: item[0])
            return {"score": score, "evidence": [{"module": "VOLATILITY", "indicator_id": identifier, "label": config_by_id[identifier]["label"], "value": metric["close"], "percentile": metric["percentile"], "change_5d": metric["change_5d"], "trend": metric["trend"], "contributions": {"absolute_threshold": absolute, "historical_percentile": adaptive, "five_day_impulse": round(impulse, 2)}, "formula": "max(绝对阈值, 历史分位, max(0, 五日变化 × 12))", "message": "绝对阈值触发" if absolute > 0 else "波动率历史分位/五日变化触发"}]}

        def equity(available):
            candidates = []
            for identifier, frame, _ in available:
                closes = frame.close.astype(float); current = float(closes.iloc[-1]); high = float(closes.tail(252).max())
                drawdown = max(0, (high - current) / high * 100)
                realized = closes.pct_change().tail(20).std() * (252 ** .5) * 100 if len(closes) >= 21 else 0
                drawdown_points = drawdown * 5; volatility_points = max(0, realized - 15) * 2; trend_points = 20 if len(closes) >= 50 and current < closes.tail(50).mean() else 0
                score = min(100, drawdown_points + volatility_points + trend_points)
                candidates.append((round(score), identifier, round(drawdown, 2), round(float(realized), 2), drawdown_points, volatility_points, trend_points))
            score, identifier, drawdown, realized, drawdown_points, volatility_points, trend_points = max(candidates)
            return {"score": score, "evidence": [{"module": "EQUITY", "indicator_id": identifier, "label": next(x["label"] for x in MARKET_INDEX_TECHNICAL_INDICATORS if x["id"] == identifier), "drawdown_pct": drawdown, "realized_volatility_pct": realized, "contributions": {"drawdown": round(drawdown_points, 2), "realized_volatility": round(volatility_points, 2), "below_50_day_trend": trend_points}, "formula": "min(100, 回撤% × 5 + max(0, 年化20日实现波动率% − 15) × 2 + 50日均线趋势加分)", "message": "回撤、实现波动率与趋势共同评估"}]}

        def directional(available, key):
            candidates = []
            for identifier, frame, direction in available:
                metric = self._frame_metric(frame, direction=direction)
                move = (metric["change_5d"] or 0) * direction
                percentile_points = (metric["percentile"] or 0) * .65; change_points = move * 8; trend_points = 10 if metric["trend"] == ("UP" if direction > 0 else "DOWN") else 0
                score = min(100, max(0, percentile_points + change_points + trend_points))
                candidates.append((round(score), identifier, metric, percentile_points, change_points, trend_points))
            score, identifier, metric, percentile_points, change_points, trend_points = max(candidates, key=lambda item: item[0])
            label = next(item["label"] for item in RISK_MODULE_INDICATORS if item["id"] == identifier)
            return {"score": score, "evidence": [{"module": key, "indicator_id": identifier, "label": label, **metric, "contributions": {"historical_percentile": round(percentile_points, 2), "five_day_change": round(change_points, 2), "trend": trend_points}, "formula": "min(100, max(0, 历史分位 × 0.65 + 方向调整后五日变化 × 8 + 趋势加分))", "message": "历史分位、五日变化与趋势共同评估"}]}

        def global_pressure(available):
            directional_inputs = [item for item in available if item[0] not in {"oil", "gold"}]
            if not directional_inputs:
                return {"score": 0, "evidence": [{"module": "GLOBAL", "label": "全球风险传导", "message": "原油与黄金仅作条件证据，不单独升级风险"}]}
            result = directional(directional_inputs, "GLOBAL")
            conditional = [identifier for identifier, _, _ in available if identifier in {"oil", "gold"}]
            if conditional: result["evidence"][0]["conditional_indicators"] = conditional
            return result

        add_module("VOLATILITY", [(item["id"], 1) for item in self._state()["config"]["indicators"]], volatility)
        add_module("EQUITY", [("sp500", -1), ("nasdaq100", -1)], equity)
        add_module("RATES", [("tlt", -1), ("tnx", 1)], lambda available: directional(available, "RATES"))
        add_module("CREDIT_LIQUIDITY", [("hyg", -1), ("lqd", -1), ("hy_oas", 1), ("ig_oas", 1), ("uup", 1)], lambda available: directional(available, "CREDIT_LIQUIDITY"))
        add_module("GLOBAL", [("oil", 1), ("gold", 1), ("yen", -1), ("bitcoin", -1)], global_pressure)
        available = [item for item in modules if item["status"] == "AVAILABLE"]
        raw_score = round(sum(item["score"] for item in available) / len(available)) if available else 0
        stressed = [item for item in available if item["score"] >= 60]
        extreme = any(item["score"] >= 90 for item in available)
        # Cross-module confirmation prevents a single noisy proxy from upgrading risk.
        target = "CRISIS" if extreme else "RISK" if len(stressed) >= 2 and raw_score >= 60 else "WATCH" if raw_score >= 35 or stressed else "NORMAL"
        prior = self._state().get("risk_state") or {}
        prior_regime = prior.get("regime", "NORMAL")
        target_rank = {"NORMAL": 0, "WATCH": 1, "RISK": 2, "CRISIS": 3}
        regime = target
        if target_rank[target] > target_rank.get(prior_regime, 0) and not extreme:
            consecutive = int(prior.get("pending_upgrade_count", 0)) + 1 if prior.get("pending_regime") == target else 1
            if consecutive < 2: regime = prior_regime
        else: consecutive = 0
        transition = "维持"
        if regime != prior_regime: transition = "升级" if target_rank[regime] > target_rank.get(prior_regime, 0) else "降级"
        providers = self._provider_health()
        for failure in failures:
            error = str(failure.get("error", ""))
            for provider in providers:
                if provider in error: providers[provider]["status"] = "FAILED"
        fresh = lambda identifier: identifier in frames and sources.get(identifier) != "STALE_CACHE"
        core_checks = {
            "VOLATILITY": any(fresh(item["id"]) for item in self._state()["config"]["indicators"]),
            "EQUITY": fresh("sp500") or fresh("nasdaq100"),
            "RATES": fresh("tnx"),
            "CREDIT_LIQUIDITY": fresh("hy_oas") or fresh("ig_oas"),
        }
        missing_core = [RISK_MODULE_LABELS[key] for key, present in core_checks.items() if not present]
        health_status = "DATA_PENDING" if missing_core else "FULL" if not failures else "PARTIAL"
        display_regime = "DATA_PENDING" if health_status == "DATA_PENDING" else regime
        if display_regime == "DATA_PENDING": transition = "数据待确认：" + "、".join(missing_core) + "缺少新鲜核心证据"
        indicator_sources = [
            {"id": identifier, "label": next((item["label"] for item in [*self._state()["config"]["indicators"], *MARKET_INDEX_TECHNICAL_INDICATORS, *RISK_MODULE_INDICATORS] if item["id"] == identifier), identifier), "source": source, "as_of": str(frames[identifier].iloc[-1].date), "fresh": source != "STALE_CACHE"}
            for identifier, source in sorted(sources.items()) if identifier in frames
        ]
        data_health = {"status": health_status, "available_modules": len(available), "total_modules": len(modules), "failures": failures, "sources": sorted(set(sources.values())), "providers": providers, "core_checks": core_checks, "missing_core": missing_core, "indicator_sources": indicator_sources}
        return {"risk_score": raw_score, "regime": display_regime, "raw_regime": regime, "display_regime": display_regime, "modules": modules, "evidence": evidence, "methodology": self._methodology(), "data_health": data_health, "transition": transition, "pending_regime": target, "pending_upgrade_count": consecutive, "checked_at": checked_at}

    def check(self) -> dict:
        state = self._state(); config = state["config"]; readings, index_observations, failures, frames, sources, pending_indicators, technical_candidates = [], [], [], {}, {}, [], []
        scan_indicators = [*config["indicators"], *MARKET_INDEX_TECHNICAL_INDICATORS, *RISK_MODULE_INDICATORS]
        for item in scan_indicators:
            try:
                cached = self._cached_bars(state, item)
                if cached is None: pending_indicators.append(item)
                else: frames[item["id"]], sources[item["id"]] = cached, "CACHE"
            except Exception: pending_indicators.append(item)
        executor = ThreadPoolExecutor(max_workers=min(MAX_PROVIDER_WORKERS, max(1, len(pending_indicators))), thread_name_prefix="market-alert")
        futures = {executor.submit(self._fetch_indicator, item): item for item in pending_indicators}
        completed, pending = wait(futures, timeout=self.fetch_timeout_seconds)
        for future in completed:
            item = futures[future]
            try:
                raw, provider = future.result(); bars = self._completed_bars(raw); frames[item["id"]], sources[item["id"]] = bars, provider
                state["market_cache"][item["id"]] = {"code": item["code"], "provider": provider, "fetched_at": self.now().isoformat(), "bars": bars.to_dict(orient="records")}
            except Exception as error:
                stale = self._stale_cached_bars(state, item)
                if stale:
                    bars, age = stale; frames[item["id"]], sources[item["id"]] = bars, "STALE_CACHE"
                    failures.append({"id": item["id"], "label": item["label"], "code": item["code"], "error": str(error), "fallback": "STALE_CACHE", "cache_age_seconds": round(age)})
                else: failures.append({"id": item["id"], "label": item["label"], "code": item["code"], "error": str(error)})
        for future in pending:
            item = futures[future]; future.cancel()
            stale = self._stale_cached_bars(state, item)
            if stale:
                bars, age = stale; frames[item["id"]], sources[item["id"]] = bars, "STALE_CACHE"
                failures.append({"id": item["id"], "label": item["label"], "code": item["code"], "error": f"providers timed out after {self.fetch_timeout_seconds:g}s", "fallback": "STALE_CACHE", "cache_age_seconds": round(age)})
            else: failures.append({"id": item["id"], "label": item["label"], "code": item["code"], "error": f"providers timed out after {self.fetch_timeout_seconds:g}s"})
        executor.shutdown(wait=False, cancel_futures=True)
        for indicator in config["indicators"]:
            frame = frames.get(indicator["id"])
            if frame is None: continue
            prior, current = frame.iloc[-2], frame.iloc[-1]
            close, change = float(current.close), (float(current.close) / float(prior.close) - 1) * 100; date = str(current.date); reasons = []
            if change >= config["change_threshold_pct"]: reasons.append({"kind": "DAILY_CHANGE", "severity": "WATCH", "message": f"单日上涨 {change:.2f}%"})
            if indicator["risk_level"] is not None and close >= indicator["risk_level"]: reasons.append({"kind": "RISK_LEVEL", "severity": "RISK", "message": f"收盘 {close:.2f} ≥ 高风险线 {indicator['risk_level']:.0f}"})
            elif indicator["watch_level"] is not None and close >= indicator["watch_level"]: reasons.append({"kind": "WATCH_LEVEL", "severity": "WATCH", "message": f"收盘 {close:.2f} ≥ 关注线 {indicator['watch_level']:.0f}"})
            readings.append({"id": indicator["id"], "label": indicator["label"], "code": indicator["code"], "source": sources[indicator["id"]], "date": date, "close": close, "change_pct": round(change, 4), "severity": self._severity(reasons), "reasons": reasons})
            try: technical_candidates.extend(self._technical_events(indicator, frame))
            except Exception as error: failures.append({"id": indicator["id"], "label": indicator["label"], "code": indicator["code"], "error": f"GPMAPRO technical scan failed: {error}"})
        for indicator in MARKET_INDEX_TECHNICAL_INDICATORS:
            frame = frames.get(indicator["id"])
            if frame is None: continue
            index_observations.append({"id": indicator["id"], "label": indicator["label"], "code": indicator["code"], "source": sources[indicator["id"]], "date": str(frame.iloc[-1].date)})
            try: technical_candidates.extend(self._technical_events(indicator, frame))
            except Exception as error: failures.append({"id": indicator["id"], "label": indicator["label"], "code": indicator["code"], "error": f"GPMAPRO technical scan failed: {error}"})
        checked_at = self.now().isoformat()
        risk_state = self._risk_snapshot(frames, sources, failures, checked_at)
        state["risk_state"] = risk_state
        risk_date = max((str(frame.iloc[-1].date) for frame in frames.values()), default=checked_at[:10])
        state["risk_history"] = [item for item in state["risk_history"] if item.get("date") != risk_date]
        state["risk_history"].append({"date": risk_date, "risk_score": risk_state["risk_score"], "regime": risk_state["regime"], "available_modules": risk_state["data_health"]["available_modules"]})
        state["risk_history"] = state["risk_history"][-RISK_HISTORY_LIMIT:]
        state["last_check"] = {"checked_at": checked_at, "status": "OK" if not failures else "PARTIAL" if readings else "FAILED", "failures": failures}
        state["observations"].extend(readings); state["observations"] = state["observations"][-500:]
        for observation in index_observations: observation["checked_at"] = checked_at
        state["market_index_observations"].extend(index_observations); state["market_index_observations"] = state["market_index_observations"][-100:]
        existing = {(alert.get("category", "VOLATILITY_LEVEL"), alert["date"], alert["indicator_id"], alert.get("signal_code") or alert.get("reason_kind")) for alert in state["alerts"]}; created = []
        for reading in readings:
            for reason in reading["reasons"]:
                key = ("VOLATILITY_LEVEL", reading["date"], reading["id"], reason["kind"])
                if key not in existing:
                    created.append({"id": f"{reading['id']}-{reading['date']}-{reason['kind']}", "category": "VOLATILITY_LEVEL", "indicator_id": reading["id"], "label": reading["label"], "date": reading["date"], "close": reading["close"], "change_pct": reading["change_pct"], "reason_kind": reason["kind"], "signal_code": reason["kind"], "signal_direction": None, "signal_date": reading["date"], "display_label": reason["message"], "severity": reason["severity"], "message": reason["message"], "created_at": checked_at, "read": False}); existing.add(key)
        for candidate in technical_candidates:
            key = (candidate["category"], candidate["date"], candidate["indicator_id"], candidate["signal_code"])
            if key not in existing:
                created.append({"id": f"{candidate['indicator_id']}-{candidate['date']}-{candidate['signal_code']}", **candidate, "close": None, "change_pct": None, "reason_kind": candidate["signal_code"], "created_at": checked_at, "read": False}); existing.add(key)
        state["alerts"].extend(created); state["alerts"] = state["alerts"][-500:]; self._save(state)
        return {"readings": readings, "failures": failures, "created_alerts": created, "last_check": state["last_check"]}

    def mark_read(self) -> dict:
        state = self._state()
        for alert in state["alerts"]: alert["read"] = True
        self._save(state); return self.snapshot()
