"""Daily, read-only market-volatility alerts using Yahoo Finance public data."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.services.gpmapro_engine import GpmaProEngine

NEW_YORK = ZoneInfo("America/New_York")
CACHE_SECONDS = 300
TECHNICAL_LOOKBACK_SESSIONS = 3
DEFAULT_INDICATORS = [
    {"id": "vix", "label": "VIX", "code": "^VIX", "watch_level": 20.0, "risk_level": 25.0},
    {"id": "vxn", "label": "VXN", "code": "^VXN", "watch_level": 25.0, "risk_level": 30.0},
    {"id": "vvix", "label": "VVIX", "code": "^VVIX", "watch_level": None, "risk_level": None},
    {"id": "vixy", "label": "VIXY", "code": "VIXY", "watch_level": None, "risk_level": None},
]
MARKET_INDEX_TECHNICAL_INDICATORS = [
    {"id": "sp500", "label": "标普 500", "code": "^GSPC", "asset_type": "MARKET_INDEX"},
    {"id": "nasdaq100", "label": "纳斯达克 100", "code": "^NDX", "asset_type": "MARKET_INDEX"},
    {"id": "nasdaq_composite", "label": "纳斯达克综合指数", "code": "^IXIC", "asset_type": "MARKET_INDEX"},
]
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
        self.fetcher = fetcher or self._fetch_yahoo_daily_bars
        self.fetch_timeout_seconds, self.now = fetch_timeout_seconds, now or (lambda: datetime.now(UTC))

    @staticmethod
    def _default_state() -> dict:
        return {"config": {"provider": "YAHOO_FINANCE", "change_threshold_pct": 3.0, "indicators": DEFAULT_INDICATORS}, "market_cache": {}, "observations": [], "market_index_observations": [], "alerts": [], "last_check": None}

    def _state(self) -> dict:
        if not self.path.exists(): return self._default_state()
        try: state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return self._default_state()
        legacy = state.get("config", {}).get("provider") != "YAHOO_FINANCE" or any(item.get("id") == "vxmain" for item in state.get("config", {}).get("indicators", []))
        if legacy:
            threshold = state.get("config", {}).get("change_threshold_pct", 3.0)
            state["config"] = {"provider": "YAHOO_FINANCE", "change_threshold_pct": threshold, "indicators": DEFAULT_INDICATORS}; state["market_cache"] = {}
        state.setdefault("market_cache", {}); state.setdefault("observations", []); state.setdefault("market_index_observations", []); state.setdefault("alerts", []); state.setdefault("last_check", None)
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
        return {"config": state["config"], "observations": state["observations"][-20:], "alerts": alerts, "active_alerts": active_alerts, "technical_signals": volatility_technical, "market_index_technical_signals": market_index_technical, "market_index_technical_indicators": MARKET_INDEX_TECHNICAL_INDICATORS, "market_index_last_check": list(index_latest.values()), "technical_lookback_sessions": TECHNICAL_LOOKBACK_SESSIONS, "last_check": state["last_check"]}

    def _fetch_yahoo_daily_bars(self, symbol: str) -> pd.DataFrame:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        try:
            response = httpx.get(url, params={"range": "2y", "interval": "1d", "includePrePost": "false", "events": "history"}, timeout=self.fetch_timeout_seconds, headers={"User-Agent": "DELTA-Time-Space/1.0"})
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
        data = frame.copy(); data["date"] = pd.to_datetime(data["date"]).dt.date; data = data.dropna(subset=["close"]).sort_values("date")
        now_ny = self.now().astimezone(NEW_YORK)
        if now_ny.time() < time(16, 15): data = data[data["date"] < now_ny.date()]
        if len(data) < 2: raise ValueError("at least two completed daily closes are required")
        data["date"] = data["date"].astype(str)
        return data

    def _fetch_one_with_timeout(self, code: str) -> pd.DataFrame:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-alert-validate")
        future = executor.submit(self.fetcher, code); completed, _ = wait([future], timeout=self.fetch_timeout_seconds); executor.shutdown(wait=False, cancel_futures=True)
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
                bars = self._fetch_one_with_timeout(item["code"])
                cache[item["id"]] = {"code": item["code"], "fetched_at": self.now().isoformat(), "bars": bars.to_dict(orient="records")}
            except Exception as error: raise ValueError(f"unable to validate {item['label']} ({item['code']}): {error}") from error
        state["config"] = {"provider": "YAHOO_FINANCE", "change_threshold_pct": threshold, "indicators": cleaned}; state["market_cache"] = cache; self._save(state)
        return self.snapshot()

    def _cached_bars(self, state: dict, indicator: dict) -> pd.DataFrame | None:
        entry = state["market_cache"].get(indicator["id"])
        if not entry or entry.get("code") != indicator["code"]: return None
        try: age = (self.now() - datetime.fromisoformat(entry["fetched_at"])).total_seconds()
        except (TypeError, ValueError): return None
        return self._completed_bars(pd.DataFrame(entry["bars"])) if age < CACHE_SECONDS else None

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

    def check(self) -> dict:
        state = self._state(); config = state["config"]; readings, index_observations, failures, frames, sources, pending_indicators, technical_candidates = [], [], [], {}, {}, [], []
        scan_indicators = [*config["indicators"], *MARKET_INDEX_TECHNICAL_INDICATORS]
        for item in scan_indicators:
            try:
                cached = self._cached_bars(state, item)
                if cached is None: pending_indicators.append(item)
                else: frames[item["id"]], sources[item["id"]] = cached, "CACHE"
            except Exception: pending_indicators.append(item)
        executor = ThreadPoolExecutor(max_workers=max(1, len(pending_indicators)), thread_name_prefix="market-alert")
        futures = {executor.submit(self.fetcher, item["code"]): item for item in pending_indicators}
        completed, pending = wait(futures, timeout=self.fetch_timeout_seconds)
        for future in completed:
            item = futures[future]
            try:
                bars = self._completed_bars(future.result()); frames[item["id"]], sources[item["id"]] = bars, "YAHOO_FINANCE"
                state["market_cache"][item["id"]] = {"code": item["code"], "fetched_at": self.now().isoformat(), "bars": bars.to_dict(orient="records")}
            except Exception as error: failures.append({"id": item["id"], "label": item["label"], "code": item["code"], "error": str(error)})
        for future in pending:
            item = futures[future]; future.cancel(); failures.append({"id": item["id"], "label": item["label"], "code": item["code"], "error": f"Yahoo Finance request timed out after {self.fetch_timeout_seconds:g}s"})
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
        checked_at = self.now().isoformat(); state["last_check"] = {"checked_at": checked_at, "status": "OK" if not failures else "PARTIAL" if readings else "FAILED", "failures": failures}
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
