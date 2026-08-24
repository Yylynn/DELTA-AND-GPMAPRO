"""Point-in-time news-factor snapshots and research-only candidate ranking."""
from __future__ import annotations

from datetime import datetime, time as dt_time, timezone
from math import exp
import json
from pathlib import Path
from threading import RLock
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from app.config.news_universe import RESEARCH_UNIVERSE
from app.data.providers import CsvDataProvider
from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmapro_engine import GpmaProEngine
from app.services.news import NewsService
from app.services.news_advice import NewsFactorCalculator
from app.services.trading_calendar import is_session

NY = ZoneInfo("America/New_York")


class NewsFactorService:
    def __init__(self, news: NewsService, root: Path, evaluation=None, now: Callable[[], datetime] | None = None) -> None:
        self.news, self.root = news, root
        self.evaluation = evaluation
        self.provider = CsvDataProvider(root.parent / "imported")
        self.gpma = GpmaProEngine()
        self.snapshot_root = root.parent / "news_factor_snapshots"
        self.calculator = NewsFactorCalculator()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._snapshot_lock = RLock()

    def _symbols(self) -> list[str]:
        return list(RESEARCH_UNIVERSE)

    def _market_filter(self, all_items: list[dict], captured_at: str | None = None) -> dict:
        now = pd.Timestamp(captured_at or self._now().isoformat()).to_pydatetime()
        values, sources = [], set()
        for item in all_items:
            if item.get("scope") != "MARKET" or not item.get("published_at"): continue
            try: hours = max(0, (now - pd.Timestamp(item["published_at"]).to_pydatetime()).total_seconds() / 3600)
            except (TypeError, ValueError): continue
            values.append(float(item.get("analysis", {}).get("sentiment_score", 0)) * exp(-hours / 36))
            sources.add(item.get("source_id"))
        score = sum(values) / len(values) if values else 0.0
        risk = "RED" if len(sources) >= 2 and score <= -.30 else "AMBER" if score <= -.15 else "NEUTRAL"
        return {"status": risk, "score": round(score, 4), "source_count": len(sources)}

    def _technical(self, symbol: str) -> dict:
        try:
            bars, _ = self.provider.ohlcv(symbol)
            data = self.gpma.calculate(bars).reset_index(drop=True)
            row = data.iloc[-1]
            bullish = bool(row.bull_bg)
            active_b = bool(row[["b1", "b2", "b3"]].any())
            delta_low = False
            if len(data) >= 118:
                today = pd.Timestamp(data.date.iloc[-1]).date().isoformat()
                delta_low = any(event["event_type"] == "LOW" and event["window_start"] <= today <= event["window_end"] for event in ITDDeltaEngine().signal_windows(data))
            return {"status": "AVAILABLE", "gpma_bullish": bullish, "gpma_active_buy": active_b, "delta_low_active": delta_low, "as_of": str(data.date.iloc[-1])}
        except Exception as error:
            return {"status": "UNAVAILABLE", "reason": str(error), "gpma_bullish": False, "gpma_active_buy": False, "delta_low_active": False}

    @staticmethod
    def _components(response: dict, captured_at: str, history_counts: list[float] | None = None) -> dict:
        return NewsFactorCalculator().calculate(response, captured_at, history_counts=history_counts or [])

    def _v3_snapshots(self, *, include_invalid: bool = True) -> list[dict]:
        rows = []
        for path in sorted(self.snapshot_root.glob("*.json")) if self.snapshot_root.exists() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("schema_version") != 3:
                continue
            if include_invalid or payload.get("quality_status") == "VALID":
                payload["_snapshot_id"] = path.stem
                rows.append(payload)
        return rows

    def _history_counts(self, symbol: str) -> list[float]:
        values = []
        for payload in self._v3_snapshots(include_invalid=True)[-60:]:
            feature = payload.get("features", {}).get(symbol)
            if feature:
                values.append(float(feature.get("news_count", 0)))
        return values

    def snapshot(self, *, refresh: bool = True) -> dict:
        with self._snapshot_lock:
            return self._create_snapshot(refresh=refresh)

    def _create_snapshot(self, *, refresh: bool = True) -> dict:
        captured = self._now().astimezone(timezone.utc)
        captured_at = captured.isoformat()
        session_date = captured.astimezone(NY).date().isoformat()
        existing = next((row for row in reversed(self._v3_snapshots(include_invalid=True)) if row.get("session_date") == session_date), None)
        if existing:
            return {"schema_version": 3, "snapshot_id": existing["_snapshot_id"], "captured_at": existing["captured_at"],
                    "session_date": session_date, "symbols_captured": len(existing.get("responses", [])),
                    "quality_status": existing.get("quality_status"), "failures": existing.get("failures", []),
                    "source_health": existing.get("source_health", []), "idempotent": True}
        rows, failures = [], []
        for symbol in self._symbols():
            try: rows.append(self.news.get(f"US.{symbol}", limit=100, refresh=refresh))
            except Exception as error: failures.append({"symbol": symbol, "error": str(error)})
        components = {row["symbol"]: self._components(row, captured_at, self._history_counts(row["symbol"])) for row in rows}
        eligible_symbols = sum(value.get("data_quality", {}).get("valid_article_count", 0) > 0 for value in components.values())
        captured_ratio = len(rows) / max(1, len(RESEARCH_UNIVERSE))
        quality_status = "VALID" if captured_ratio >= .7 and eligible_symbols >= 10 else "INSUFFICIENT_COVERAGE"
        payload = {"schema_version": 3, "quality_status": quality_status, "captured_at": captured_at,
                   "session_date": session_date, "symbols": [row["symbol"] for row in rows], "responses": rows,
                   "features": components, "failures": failures, "source_health": self.news.source_health(),
                   "coverage": {"configured": len(RESEARCH_UNIVERSE), "captured": len(rows), "captured_ratio": round(captured_ratio, 4),
                                "symbols_with_eligible_news": eligible_symbols}}
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_root / f"v3_{session_date}.json"
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            return {"schema_version": 3, "snapshot_id": path.stem, "captured_at": existing["captured_at"],
                    "session_date": session_date, "symbols_captured": len(existing.get("responses", [])),
                    "quality_status": existing.get("quality_status"), "failures": existing.get("failures", []),
                    "source_health": existing.get("source_health", []), "idempotent": True}
        return {"schema_version": 3, "snapshot_id": path.stem, "captured_at": captured_at, "session_date": session_date,
                "symbols_captured": len(rows), "quality_status": quality_status, "failures": failures,
                "source_health": payload["source_health"], "idempotent": False}

    def ensure_daily_snapshot(self, *, refresh: bool = False) -> dict:
        local = self._now().astimezone(NY)
        if not is_session(local.date()) or local.time() < dt_time(16, 15):
            return {"status": "NOT_DUE", "session_date": local.date().isoformat()}
        existing = next((row for row in reversed(self._v3_snapshots(include_invalid=True)) if row.get("session_date") == local.date().isoformat()), None)
        if existing:
            return {"status": "CURRENT", "session_date": local.date().isoformat(), "snapshot_id": existing["_snapshot_id"]}
        return {"status": "CREATED", **self.snapshot(refresh=refresh)}

    def _latest(self) -> dict | None:
        snapshots = self._v3_snapshots(include_invalid=True)
        return snapshots[-1] if snapshots else None

    def candidates(self, limit: int = 5) -> dict:
        snapshot = self._latest()
        if not snapshot: return {"status": "NO_SNAPSHOT", "candidates": [], "message": "尚未生成新闻因子快照。请先调用新闻快照接口。"}
        # `items` is intentionally company-only for backwards compatibility;
        # macro evidence lives in its own field and must feed the risk filter.
        all_items = [item for response in snapshot["responses"] for item in response.get("market_items", [])]
        market = self._market_filter(all_items, snapshot.get("captured_at"))
        validation = self.evaluation.evaluate() if self.evaluation is not None else {"status": "INSUFFICIENT_EVIDENCE"}
        validated = validation.get("status") == "VALIDATED"
        candidates = []
        for response in snapshot["responses"]:
            symbol = response["symbol"].removeprefix("US.")
            feature = snapshot.get("features", {}).get(response["symbol"], {}); score = float(feature.get("factor_score", 0))
            articles = [item for item in feature.get("evidence", []) if item.get("eligible")]
            technical = self._technical(symbol)
            negative = bool(feature.get("negative_major_event"))
            if market["status"] == "RED": tier = "FILTERED"
            elif score > 0 and technical["gpma_bullish"] and technical["gpma_active_buy"] and technical["delta_low_active"] and not negative: tier = "FOCUS"
            elif score > 0 and not negative: tier = "WATCH"
            else: tier = "FILTERED"
            research_state = "INSUFFICIENT_EVIDENCE"
            if validated: research_state = "NEGATIVE_AVOID" if negative or score <= -.15 else "POSITIVE_WATCH" if score >= .15 else "NEUTRAL"
            candidates.append({"symbol": response["symbol"], "tier": tier, "research_state": research_state, "news_score": round(score, 4), "components": feature, "article_count": len(articles), "negative_catalyst": negative, "market_risk_filter": market, "technical": technical, "earliest_trade_at": feature.get("earliest_trade_at"), "historical_prediction_confidence": None, "validation_status": validation.get("status"), "evidence": articles})
        ordered = sorted(candidates, key=lambda item: item["news_score"], reverse=True)
        return {"status": "RESEARCH_ONLY", "validation_status": validation.get("status"), "snapshot_at": snapshot["captured_at"], "snapshot_quality": snapshot.get("quality_status"), "market_risk_filter": market, "candidates": ordered[:max(1, min(limit, 20))], "universe_coverage": {"configured": len(RESEARCH_UNIVERSE), "captured": len(snapshot["responses"]), "with_local_ohlcv": len(self.provider.symbols()), "with_eligible_news": snapshot.get("coverage", {}).get("symbols_with_eligible_news", 0)}, "message": "已通过样本外统计门槛，仅输出研究观察状态。" if validated else "历史预测可信度尚未验证；未达统计门槛前仅展示证据不足。"}

    def snapshots(self) -> list[dict]:
        return [{"snapshot_id": row["_snapshot_id"], "captured_at": row.get("captured_at"), "session_date": row.get("session_date"), "schema_version": 3, "quality_status": row.get("quality_status")} for row in reversed(self._v3_snapshots(include_invalid=True))]
