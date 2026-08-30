"""Read-only, point-in-time US equity option monitoring.

The service deliberately treats option-chain data as research evidence.  A
chain snapshot cannot establish buyer/seller initiation, opening interest or
multi-leg intent, so directional labels are hypotheses, never trade orders.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.config.news_universe import RESEARCH_UNIVERSE

NY = ZoneInfo("America/New_York")
SCAN_START, SCAN_END = time(9, 35), time(15, 55)
MIN_DTE, MAX_DTE, MAX_MONEYNESS = 7, 60, 0.15
BASELINE_WINDOWS = 20


class OptionMonitorError(RuntimeError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if np.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _first(row: pd.Series | dict, *names: str, default: Any = None) -> Any:
    for name in names:
        value = row.get(name) if hasattr(row, "get") else None
        if value is not None and not (isinstance(value, float) and np.isnan(value)):
            return value
    return default


class FutuOptionClient:
    """Thin adapter so tests never need an OpenD process."""
    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host, self.port = host, port

    def _endpoint(self) -> None:
        try:
            with socket.create_connection((self.host, self.port), timeout=1):
                return
        except OSError as error:
            raise OptionMonitorError(f"OpenD is unavailable at {self.host}:{self.port}: {error}") from error

    def fetch(self, code: str, now: datetime) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
        self._endpoint()
        try:
            from futu import OpenQuoteContext, RET_OK
        except ImportError as error:  # pragma: no cover - deployment guard
            raise OptionMonitorError("Futu Python SDK is not installed") from error
        context = OpenQuoteContext(host=self.host, port=self.port)
        try:
            start, end = now.date() + timedelta(days=MIN_DTE), now.date() + timedelta(days=MAX_DTE)
            ret, chain = context.get_option_chain(code, start=start.isoformat(), end=end.isoformat())
            if ret != RET_OK:
                raise OptionMonitorError(f"OpenD option chain request failed: {chain}")
            contract_codes = [str(value) for value in chain.get("code", pd.Series(dtype=str)).tolist()]
            if not contract_codes:
                return pd.DataFrame(), pd.DataFrame(), False
            # OpenD limits snapshot batches; preserve chain order for reproducibility.
            frames = []
            for offset in range(0, len(contract_codes), 400):
                result, snapshot = context.get_market_snapshot(contract_codes[offset:offset + 400])
                if result != RET_OK:
                    raise OptionMonitorError(f"OpenD option quote request failed: {snapshot}")
                frames.append(snapshot)
            result, underlying = context.get_market_snapshot([code])
            if result != RET_OK:
                raise OptionMonitorError(f"OpenD underlying quote request failed: {underlying}")
            quotes = pd.concat(frames, ignore_index=True)
            if not underlying.empty:
                quotes["underlying_price"] = _number(_first(underlying.iloc[0], "last_price", "close_price"))
                quotes["underlying_volume"] = _number(_first(underlying.iloc[0], "volume"))
            return chain, quotes, self._has_earnings_within_week(context, code, now)
        finally:
            context.close()

    @staticmethod
    def _has_earnings_within_week(context, code: str, now: datetime) -> bool:
        """Best-effort guard only: unavailable calendars never invent an event."""
        try:
            from futu import Market
            ret, calendar = context.get_earnings_calendar(Market.US, begin_date=now.date().isoformat(), end_date=(now.date() + timedelta(days=7)).isoformat())
            if ret != 0 or calendar is None or calendar.empty:
                return False
            values = calendar.astype(str).apply(lambda col: col.str.upper().eq(code.upper()).any()).any()
            return bool(values)
        except Exception:
            return False


class OptionMonitorService:
    def __init__(self, root: Path | None = None, client: FutuOptionClient | None = None,
                 candidate_provider: Callable[[int], dict] | None = None,
                 news_provider: Callable[[str], dict] | None = None,
                 now: Callable[[], datetime] | None = None):
        self.root = root or Path(__file__).resolve().parents[3] / "data" / "option_chain_snapshots"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "monitor_state.json"
        self.client, self.candidate_provider, self.news_provider = client or FutuOptionClient(), candidate_provider, news_provider
        self.now = now or (lambda: datetime.now(UTC))
        self._lock = RLock()

    @staticmethod
    def _default_state() -> dict:
        return {"schema_version": 1, "alerts": [], "scans": [], "last_check": None, "watch_symbols": []}

    def _state(self) -> dict:
        if not self.state_path.exists(): return self._default_state()
        try: state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return self._default_state()
        for key, value in self._default_state().items(): state.setdefault(key, value)
        return state

    def _save(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def health(self) -> dict:
        try:
            self.client._endpoint() if isinstance(self.client, FutuOptionClient) else None
            status, error = "AVAILABLE", None
        except Exception as reason:
            status, error = "UNAVAILABLE", str(reason)
        scans = self._state().get("scans", [])
        return {"status": status, "source": "FUTU_OPEND", "error": error,
                "last_snapshot_at": scans[-1].get("captured_at") if scans else None,
                "snapshot_count": len(list(self.root.glob("*.csv"))),
                "limitations": ["不含逐笔成交方向、开平仓或多腿识别。", "期权信号只用于研究预警，不改变交易行动等级。"]}

    def _symbols(self, state: dict, requested: str | None = None) -> list[str]:
        candidates: list[str] = []
        if self.candidate_provider:
            try:
                candidates = [str(row.get("symbol", "")).upper().removeprefix("US.") for row in self.candidate_provider(8).get("candidates", [])]
            except Exception:
                candidates = []
        candidates.extend(state.get("watch_symbols", []))
        if requested: candidates.insert(0, requested.upper().removeprefix("US."))
        candidates.extend(RESEARCH_UNIVERSE)
        output: list[str] = []
        for symbol in candidates:
            if symbol in RESEARCH_UNIVERSE and symbol not in output:
                output.append(symbol)
            if len(output) == 8: break
        return output

    @staticmethod
    def _normalise(chain: pd.DataFrame, quotes: pd.DataFrame, code: str, captured: datetime) -> tuple[pd.DataFrame, dict]:
        if chain.empty or quotes.empty: return pd.DataFrame(), {"reason": "EMPTY_CHAIN"}
        merged = chain.merge(quotes, on="code", how="inner", suffixes=("_chain", "_quote"))
        spot = _number(_first(quotes.iloc[0], "underlying_price", "underlying_last_price"))
        if not spot:
            spot = _number(_first(chain.iloc[0], "underlying_price", "underlying_last_price"))
        rows = []
        for _, row in merged.iterrows():
            strike = _number(_first(row, "strike_price", "strike_price_chain"))
            expiry = _first(row, "strike_time", "expiry_date", "expiration_date", "strike_time_chain")
            try: expiry_date = pd.Timestamp(expiry).date()
            except Exception: continue
            dte = (expiry_date - captured.date()).days
            bid, ask = _number(_first(row, "bid_price", "bid_price_quote")), _number(_first(row, "ask_price", "ask_price_quote"))
            if not (spot > 0 and strike > 0 and MIN_DTE <= dte <= MAX_DTE and abs(strike / spot - 1) <= MAX_MONEYNESS and bid > 0 and ask >= bid): continue
            option_type = str(_first(row, "option_type", "option_type_chain", default="")).upper()
            rows.append({"symbol": code, "contract": str(_first(row, "code")), "captured_at": captured.isoformat(),
                         "spot": spot, "stock_volume": _number(_first(row, "underlying_volume", "underlying_volume_quote")),
                         "option_type": "CALL" if "CALL" in option_type else "PUT" if "PUT" in option_type else option_type,
                         "strike": strike, "expiry": expiry_date.isoformat(), "dte": dte, "bid": bid, "ask": ask,
                         "last": _number(_first(row, "last_price", "last_price_quote")), "volume": _number(_first(row, "volume", "volume_quote")),
                         "open_interest": _number(_first(row, "open_interest", "open_interest_quote")),
                         "iv": _number(_first(row, "implied_volatility", "option_implied_volatility", "implied_volatility_quote")),
                         "delta": _number(_first(row, "delta", "option_delta", "delta_quote")),
                         "gamma": _number(_first(row, "gamma", "option_gamma", "gamma_quote")),
                         "vega": _number(_first(row, "vega", "option_vega", "vega_quote"))})
        return pd.DataFrame(rows), {"spot": spot, "raw_contracts": len(merged), "eligible_contracts": len(rows)}

    def _history(self, symbol: str, clock: datetime) -> list[dict]:
        rows = []
        for path in sorted(self.root.glob("*.csv"))[-300:]:
            try:
                frame = pd.read_csv(path)
                frame = frame[frame.symbol.eq(symbol)]
                if frame.empty: continue
                captured = pd.Timestamp(frame.captured_at.iloc[0]).to_pydatetime().astimezone(NY)
                if captured.strftime("%H:%M") == clock.astimezone(NY).strftime("%H:%M"):
                    rows.append(self._aggregate(frame))
            except Exception: continue
        return rows[-BASELINE_WINDOWS:]

    @staticmethod
    def _aggregate(frame: pd.DataFrame) -> dict:
        calls, puts = frame[frame.option_type.eq("CALL")], frame[frame.option_type.eq("PUT")]
        atm = frame.assign(distance=(frame.strike / frame.spot - 1).abs()).sort_values("distance").head(max(1, min(20, len(frame))))
        def weighted(column: str) -> float:
            weights = atm.volume.clip(lower=1)
            return float(np.average(atm[column], weights=weights)) if len(atm) else 0.0
        premium = ((frame.bid + frame.ask) / 2 * frame.volume * 100).sum()
        return {"captured_at": str(frame.captured_at.iloc[0]), "symbol": str(frame.symbol.iloc[0]), "spot": _number(frame.spot.iloc[0]),
                "stock_volume": _number(frame.stock_volume.max()), "option_volume": _number(frame.volume.sum()), "premium": _number(premium),
                "call_volume": _number(calls.volume.sum()), "put_volume": _number(puts.volume.sum()), "atm_iv": weighted("iv"),
                "near_iv": weighted("iv"), "far_iv": float(np.average(frame.loc[frame.dte >= 30, "iv"], weights=frame.loc[frame.dte >= 30, "volume"].clip(lower=1))) if (frame.dte >= 30).any() else 0.0,
                "top_contract": str(frame.sort_values("volume", ascending=False).contract.iloc[0]) if len(frame) else None,
                "top_strike": _number(frame.sort_values("volume", ascending=False).strike.iloc[0]) if len(frame) else None}

    @staticmethod
    def _zscore(value: float, history: list[dict], key: str) -> float | None:
        values = np.array([_number(row.get(key)) for row in history], dtype=float)
        if len(values) < BASELINE_WINDOWS: return None
        median = float(np.median(values)); mad = float(np.median(np.abs(values - median)))
        return 0.0 if mad == 0 else round(.6745 * (value - median) / mad, 4)

    def _signals(self, aggregate: dict, history: list[dict], scheduled: bool) -> list[dict]:
        relative = aggregate["option_volume"] / max(aggregate["stock_volume"], 1)
        premium_z, iv_z = self._zscore(aggregate["premium"], history, "premium"), self._zscore(aggregate["atm_iv"], history, "atm_iv")
        signals = []
        if premium_z is None:
            return [{"kind": "WARMING_UP", "severity": "INFO", "confidence": 0.0, "message": f"同时间窗基线 {len(history)}/{BASELINE_WINDOWS}，暂不判定异常。"}]
        if premium_z >= 3 or relative >= .12:
            signals.append({"kind": "ATTENTION_SURGE", "severity": "WATCH", "confidence": .45, "message": "期权相对活跃度或权利金显著高于同时间窗基线。", "z_score": premium_z})
        if iv_z is not None and iv_z >= 3:
            signals.append({"kind": "VOLATILITY_REPRICE", "severity": "WATCH", "confidence": .45, "message": "近 ATM 隐含波动率显著重定价。", "z_score": iv_z})
        imbalance = (aggregate["call_volume"] - aggregate["put_volume"]) / max(aggregate["call_volume"] + aggregate["put_volume"], 1)
        if signals and abs(imbalance) >= .35:
            direction = "BULLISH_HYPOTHESIS" if imbalance > 0 else "BEARISH_HYPOTHESIS"
            signals.append({"kind": "DIRECTIONAL_HYPOTHESIS", "severity": "INFO" if scheduled else "WATCH", "confidence": .2 if scheduled else .35,
                            "direction": direction, "message": "Call/Put 结构仅形成方向假设；未获逐笔方向、开平仓或多腿信息。"})
        if scheduled:
            for signal in signals:
                signal["scheduled_event"] = True
                if signal["kind"] == "DIRECTIONAL_HYPOTHESIS": signal["severity"], signal["confidence"] = "INFO", min(.2, signal["confidence"])
        return signals or [{"kind": "NORMAL", "severity": "INFO", "confidence": 0.0, "message": "当前未检测到研究级期权异常。"}]

    def _news_relation(self, symbol: str, first_alert_at: str | None, captured: datetime) -> dict:
        if not first_alert_at or not self.news_provider: return {"kind": "NO_ASSOCIATION", "message": "尚无可比对的公司新闻时间。"}
        try:
            items = self.news_provider(f"US.{symbol}").get("company_items", [])
            times = [pd.Timestamp(item.get("available_at") or item.get("published_at")) for item in items if item.get("available_at") or item.get("published_at")]
            if not times: return {"kind": "OPTION_LEADS", "message": "期权异常先出现；尚无可比对公司新闻。"}
            news_at, option_at = min(times), pd.Timestamp(first_alert_at)
            delta = (option_at - news_at).total_seconds()
            if abs(delta) <= 30 * 60: kind = "COINCIDENT"
            else: kind = "OPTION_LEADS" if delta < 0 else "NEWS_LEADS"
            return {"kind": kind, "option_first_at": first_alert_at, "news_first_at": news_at.isoformat(), "message": "仅描述时间先后，不推断因果。"}
        except Exception:
            return {"kind": "NO_ASSOCIATION", "message": "新闻时间线暂不可用。"}

    def check(self, requested: str | None = None, force: bool = True) -> dict:
        with self._lock:
            captured, state = self.now().astimezone(UTC), self._state()
            local = captured.astimezone(NY)
            if not force and (local.weekday() >= 5 or not (SCAN_START <= local.time() <= SCAN_END)):
                return {"status": "NOT_DUE", "checked_at": captured.isoformat(), "message": "仅在纽约常规盘 09:35–15:55 自动扫描。"}
            symbols, created, failures = self._symbols(state, requested), [], []
            for symbol in symbols:
                try:
                    chain, quotes, scheduled = self.client.fetch(f"US.{symbol}", captured)
                    frame, quality = self._normalise(chain, quotes, symbol, captured)
                    if frame.empty:
                        failures.append({"symbol": symbol, "error": quality.get("reason", "NO_ELIGIBLE_CONTRACTS")}); continue
                    digest = hashlib.sha256(frame.to_csv(index=False, lineterminator="\n").encode()).hexdigest()
                    snapshot_id = f"US_{symbol}_{captured.strftime('%Y%m%dT%H%M%SZ')}"
                    csv_path, manifest_path = self.root / f"{snapshot_id}.csv", self.root / f"{snapshot_id}.json"
                    frame.to_csv(csv_path, index=False)
                    aggregate, history = self._aggregate(frame), self._history(symbol, captured)
                    signals = self._signals(aggregate, history, scheduled)
                    manifest = {"schema_version": 1, "snapshot_id": snapshot_id, "source": "futu_opend", "symbol": f"US.{symbol}", "captured_at": captured.isoformat(), "sha256": digest, "scheduled_event": scheduled, "quality": quality, "aggregate": aggregate, "signals": signals}
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                    if any(signal["kind"] in {"ATTENTION_SURGE", "VOLATILITY_REPRICE"} for signal in signals):
                        relation = self._news_relation(symbol, captured.isoformat(), captured)
                        alert = {"id": snapshot_id, "symbol": f"US.{symbol}", "snapshot_id": snapshot_id, "created_at": captured.isoformat(), "read": False, "scheduled_event": scheduled, "signals": signals, "relation": relation, "aggregate": aggregate}
                        if not any(item["id"] == alert["id"] for item in state["alerts"]): created.append(alert)
                except Exception as error:
                    failures.append({"symbol": symbol, "error": str(error)})
            state["alerts"].extend(created); state["alerts"] = state["alerts"][-500:]
            state["scans"].append({"captured_at": captured.isoformat(), "symbols": [f"US.{item}" for item in symbols], "created_alerts": len(created), "failures": failures}); state["scans"] = state["scans"][-500:]
            state["last_check"] = state["scans"][-1]; self._save(state)
            return {"status": "OK" if not failures else "PARTIAL", "checked_at": captured.isoformat(), "symbols": symbols, "created_alerts": created, "failures": failures}

    def snapshot(self) -> dict:
        state = self._state()
        return {"health": self.health(), "last_check": state["last_check"], "alerts": list(reversed(state["alerts"][-50:])), "unread_count": sum(not item.get("read") for item in state["alerts"]), "coverage": {"configured": len(RESEARCH_UNIVERSE), "max_per_scan": 8}}

    def insight(self, code: str) -> dict:
        symbol = code.upper().removeprefix("US.")
        manifests = []
        for path in sorted(self.root.glob(f"US_{symbol}_*.json"), reverse=True)[:40]:
            try: manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): continue
        if not manifests: return {"symbol": f"US.{symbol}", "status": "NO_SNAPSHOT", "message": "尚未采集该标的期权快照。"}
        latest = manifests[0]; first_abnormal = next((item["captured_at"] for item in reversed(manifests) if any(signal.get("kind") in {"ATTENTION_SURGE", "VOLATILITY_REPRICE"} for signal in item.get("signals", []))), None)
        try:
            contracts = pd.read_csv(self.root / f"{latest['snapshot_id']}.csv").sort_values("volume", ascending=False).head(12).to_dict(orient="records")
        except Exception:
            contracts = []
        return {"symbol": f"US.{symbol}", "status": "AVAILABLE", "latest": latest, "contracts": contracts, "history": [{"captured_at": item["captured_at"], **item.get("aggregate", {})} for item in reversed(manifests)], "relation": self._news_relation(symbol, first_abnormal, pd.Timestamp(latest["captured_at"]).to_pydatetime()), "limitations": ["未包含逐笔成交方向、开平仓及多腿识别。", "方向标签是研究假设，不构成交易指令。"]}
