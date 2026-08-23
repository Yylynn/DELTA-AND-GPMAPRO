"""Point-in-time news-factor snapshots and research-only candidate ranking."""
from __future__ import annotations

from datetime import datetime, timezone
from math import exp
import json
from pathlib import Path

import pandas as pd

from app.config.news_universe import RESEARCH_UNIVERSE
from app.data.providers import CsvDataProvider
from app.quant.delta_time import ITDDeltaEngine
from app.services.gpmapro_engine import GpmaProEngine
from app.services.news import NewsService

EVENT_WEIGHT = {"EARNINGS": 1.0, "GUIDANCE": 1.0, "M&A": .9, "REGULATION": .9, "LEGAL": .9, "PRODUCT": .65, "ANALYST_RATING": .6, "OTHER": .35}


class NewsFactorService:
    def __init__(self, news: NewsService, root: Path, evaluation=None) -> None:
        self.news, self.root = news, root
        self.evaluation = evaluation
        self.provider = CsvDataProvider(root.parent / "imported")
        self.gpma = GpmaProEngine()
        self.snapshot_root = root.parent / "news_factor_snapshots"

    def _symbols(self) -> list[str]:
        return list(RESEARCH_UNIVERSE)

    def _market_filter(self, all_items: list[dict]) -> dict:
        now = datetime.now(timezone.utc)
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
    def _components(response: dict, captured_at: str) -> dict:
        now = pd.Timestamp(captured_at); eligible = []
        for item in response.get("company_items", response.get("items", [])):
            if not item.get("factor_eligible") or not item.get("published_at") or not item.get("earliest_trade_at"): continue
            age = max(0.0, (now - pd.Timestamp(item["published_at"])).total_seconds() / 3600)
            analysis = item.get("analysis", {}); relevance = 1.0 if item.get("entity_matches") else 0.0
            weight = exp(-age / 72) * EVENT_WEIGHT.get(analysis.get("event_type", "OTHER"), .35) * relevance
            eligible.append((item, float(analysis.get("sentiment_score", 0)), weight))
        denominator = sum(weight for _, _, weight in eligible)
        sentiment = sum(score * weight for _, score, weight in eligible) / denominator if denominator else 0.0
        negative = any(item.get("analysis", {}).get("high_impact") and item.get("analysis", {}).get("direction") == "BEARISH" for item, _, _ in eligible)
        published = [item for item in response.get("company_items", []) if item.get("published_at")]
        sources = {item.get("source_id") for item, _, _ in eligible if item.get("source_id")}
        return {"company_sentiment": round(sentiment, 6), "news_count": len(eligible), "news_intensity": 0.0,
                "negative_major_event": negative, "earliest_trade_at": min((item["earliest_trade_at"] for item, _, _ in eligible), default=None),
                "data_quality": {"valid_article_count": len(eligible), "source_count": len(sources), "sources": sorted(sources),
                                 "published_at_completeness": round(len(published) / max(1, len(response.get("company_items", []))), 4),
                                 "model_status": "FINBERT" if eligible else "NO_ELIGIBLE_MODEL_OUTPUT",
                                 "coverage_gaps": [source for source in ("openbb_yfinance", "sec_edgar", "finnhub_company") if source not in sources]}}

    def snapshot(self, *, refresh: bool = True) -> dict:
        captured_at = datetime.now(timezone.utc).isoformat()
        rows, failures = [], []
        for symbol in self._symbols():
            try: rows.append(self.news.get(f"US.{symbol}", limit=100, refresh=refresh))
            except Exception as error: failures.append({"symbol": symbol, "error": str(error)})
        components = {row["symbol"]: self._components(row, captured_at) for row in rows}
        counts = pd.Series({symbol: value["news_count"] for symbol, value in components.items()}, dtype=float)
        std = float(counts.std(ddof=0))
        for symbol, value in components.items():
            value["news_intensity"] = round((value["news_count"] - float(counts.mean())) / std, 6) if std else 0.0
            value["baseline_score"] = round((value["company_sentiment"] + value["news_intensity"] - float(value["negative_major_event"])) / 3, 6)
        payload = {"schema_version": 2, "quality_status": "VALID", "captured_at": captured_at, "symbols": [row["symbol"] for row in rows], "responses": rows, "features": components, "failures": failures, "source_health": self.news.source_health()}
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_root / f"{captured_at.replace(':', '-').replace('+', '_')}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"schema_version": 2, "snapshot_id": path.stem, "captured_at": captured_at, "symbols_captured": len(rows), "failures": failures, "source_health": payload["source_health"]}

    def _latest(self) -> dict | None:
        files = sorted(self.snapshot_root.glob("*.json"), reverse=True) if self.snapshot_root.exists() else []
        for path in files:
            try: payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): continue
            if payload.get("schema_version") == 2 and payload.get("quality_status") == "VALID": return payload
        return None

    def candidates(self, limit: int = 5) -> dict:
        snapshot = self._latest()
        if not snapshot: return {"status": "NO_SNAPSHOT", "candidates": [], "message": "尚未生成新闻因子快照。请先调用新闻快照接口。"}
        # `items` is intentionally company-only for backwards compatibility;
        # macro evidence lives in its own field and must feed the risk filter.
        all_items = [item for response in snapshot["responses"] for item in response.get("market_items", [])]
        market = self._market_filter(all_items)
        validation = self.evaluation.evaluate() if self.evaluation is not None else {"status": "INSUFFICIENT_EVIDENCE"}
        validated = validation.get("status") == "VALIDATED"
        now = datetime.now(timezone.utc); candidates = []
        for response in snapshot["responses"]:
            symbol = response["symbol"].removeprefix("US.")
            articles = []
            for item in response.get("items", []):
                if item.get("scope") != "COMPANY" or item.get("entity_status") != "ACCEPTED" or not item.get("published_at"): continue
                try: age = max(0, (now - pd.Timestamp(item["published_at"]).to_pydatetime()).total_seconds() / 3600)
                except (TypeError, ValueError): continue
                if age > 24: continue
                analysis = item.get("analysis", {})
                if analysis.get("method") != "FINBERT": continue
                articles.append((item, float(analysis.get("sentiment_score", 0)) * EVENT_WEIGHT.get(analysis.get("event_type", "OTHER"), .35) * exp(-age / 36)))
            feature = snapshot.get("features", {}).get(response["symbol"], {}); score = float(feature.get("baseline_score", 0))
            technical = self._technical(symbol)
            negative = any(item.get("analysis", {}).get("high_impact") and item.get("analysis", {}).get("direction") == "BEARISH" for item, _ in articles)
            if market["status"] == "RED": tier = "FILTERED"
            elif score > 0 and technical["gpma_bullish"] and technical["gpma_active_buy"] and technical["delta_low_active"] and not negative: tier = "FOCUS"
            elif score > 0 and not negative: tier = "WATCH"
            else: tier = "FILTERED"
            research_state = "INSUFFICIENT_EVIDENCE"
            if validated: research_state = "NEGATIVE_AVOID" if negative or score <= -.15 else "POSITIVE_WATCH" if score >= .15 else "NEUTRAL"
            candidates.append({"symbol": response["symbol"], "tier": tier, "research_state": research_state, "news_score": round(score, 4), "components": feature, "article_count": len(articles), "negative_catalyst": negative, "market_risk_filter": market, "technical": technical, "earliest_trade_at": feature.get("earliest_trade_at"), "historical_prediction_confidence": None, "validation_status": validation.get("status"), "evidence": [{key: item.get(key) for key in ("id", "title", "url", "publisher", "published_at", "available_at", "earliest_trade_at", "analysis", "entity_matches")} for item, _ in articles]})
        ordered = sorted(candidates, key=lambda item: item["news_score"], reverse=True)
        return {"status": "RESEARCH_ONLY", "validation_status": validation.get("status"), "snapshot_at": snapshot["captured_at"], "market_risk_filter": market, "candidates": ordered[:max(1, min(limit, 20))], "universe_coverage": {"configured": len(RESEARCH_UNIVERSE), "captured": len(snapshot["responses"]), "with_local_ohlcv": len(self.provider.symbols())}, "message": "已通过样本外统计门槛，仅输出研究观察状态。" if validated else "历史预测可信度尚未验证；未达统计门槛前仅展示证据不足。"}

    def snapshots(self) -> list[dict]:
        return [{"snapshot_id": path.stem, "captured_at": path.stem.replace("_", "+").replace("-", ":", 2)} for path in sorted(self.snapshot_root.glob("*.json"), reverse=True)] if self.snapshot_root.exists() else []
