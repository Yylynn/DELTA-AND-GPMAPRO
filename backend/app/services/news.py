"""Read-only, traceable company and market news with a local cache."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
from pathlib import Path
import re
from typing import Any, Callable, Protocol
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.config.news_sources import NewsSource, enabled_sources, resolve_source
from app.services.news_analysis import NewsAnalyzer, freshness_weight


class NewsProvider(Protocol):
    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]: ...


class OpenBBNewsProvider:
    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        from openbb import obb
        return obb.news.company(symbol=symbol, limit=limit).to_dataframe().to_dict(orient="records")


class PublicRssNewsProvider:
    """Fetch only publisher-provided RSS metadata; article pages are never fetched."""
    def __init__(self, sources: tuple[NewsSource, ...], timeout_seconds: float = 15) -> None:
        self.sources = tuple(item for item in sources if item.collector == "RSS" and item.rss_url)
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _text(item: ElementTree.Element, *names: str) -> str | None:
        for name in names:
            found = item.find(name)
            if found is not None and found.text:
                return found.text.strip()
        return None

    def market_news(self, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; DELTA-NewsCenter/1.0)"}) as client:
            for source in self.sources:
                try:
                    response = client.get(source.rss_url)
                    response.raise_for_status()
                    root = ElementTree.fromstring(response.content)
                    for item in root.findall(".//item")[:limit]:
                        title = self._text(item, "title")
                        if title:
                            rows.append({"title": title, "url": self._text(item, "link"), "date": self._text(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date"), "source": source.display_name, "scope": "MARKET"})
                except (httpx.HTTPError, ElementTree.ParseError, ValueError) as error:
                    warnings.append(f"{source.display_name} RSS 暂时不可用：{error}")
        return rows, warnings


class DefaultNewsProvider(OpenBBNewsProvider):
    def __init__(self, sources: tuple[NewsSource, ...], timeout_seconds: float = 15) -> None:
        self.rss = PublicRssNewsProvider(sources, timeout_seconds)

    def market_news(self, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        return self.rss.market_news(limit)


class NewsError(ValueError): pass
_FUTU_CODE = re.compile(r"^(US|HK)\.([A-Z0-9._-]+)$")


def provider_symbol(code: str) -> str:
    match = _FUTU_CODE.fullmatch(code.strip().upper())
    if not match: raise NewsError("仅支持美股或港股富途代码，例如 US.AAPL、HK.00700")
    market, symbol = match.groups()
    if market == "US": return symbol
    if not symbol.isdigit() or len(symbol) > 5: raise NewsError("港股代码应为 1 至 5 位数字，例如 HK.00700")
    return f"{int(symbol):04d}.HK"


def _timestamp(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)): return None
    try:
        stamp = pd.Timestamp(value)
        return (stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp).isoformat()
    except (TypeError, ValueError): return None


def normalize_records(rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        title = str(row.get("title") or row.get("headline") or "").strip()
        if not title: continue
        url = str(row.get("url") or row.get("link") or "").strip() or None
        published_at = _timestamp(row.get("date") or row.get("published_at") or row.get("published"))
        source = str(row.get("source") or row.get("publisher") or "OpenBB").strip() or "OpenBB"
        identity = f"{source}|{url or title}|{published_at or ''}"
        deduped.setdefault(identity, {"id": sha1(identity.encode()).hexdigest()[:16], "symbol": symbol, "title": title, "url": url, "source": source, "published_at": published_at, "summary": str(row.get("summary") or row.get("description") or row.get("text") or "").strip() or None, "scope": row.get("scope", "COMPANY")})
    return sorted(deduped.values(), key=lambda item: item["published_at"] or "", reverse=True)


class NewsService:
    def __init__(self, cache_dir: Path, ttl_seconds: int = 900, provider: NewsProvider | None = None, now: Callable[[], datetime] | None = None, *, sources: tuple[NewsSource, ...] | None = None, rss_timeout_seconds: float = 15) -> None:
        self.cache_dir, self.ttl = cache_dir, timedelta(seconds=max(0, ttl_seconds))
        self.sources = sources or enabled_sources()
        self.provider = provider or DefaultNewsProvider(self.sources, rss_timeout_seconds)
        self._now, self.analyzer = now or (lambda: datetime.now(timezone.utc)), NewsAnalyzer()

    def _path(self, code: str) -> Path: return self.cache_dir / f"{code.replace('.', '_')}.json"
    def _read_cache(self, code: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._path(code).read_text(encoding="utf-8"))
            return data if isinstance(data.get("items"), list) and data.get("fetched_at") else None
        except (OSError, json.JSONDecodeError): return None
    def _write_cache(self, code: str, payload: dict[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True); self._path(code).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    def _write_history(self, code: str, payload: dict[str, Any]) -> None:
        folder = self.cache_dir.parent / "news_history" / code.replace(".", "_"); folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{payload['fetched_at'].replace(':', '-').replace('+', '_')}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    def _fresh(self, cached: dict[str, Any]) -> bool:
        try:
            fetched = datetime.fromisoformat(str(cached["fetched_at"]).replace("Z", "+00:00")); return self._now() - (fetched if fetched.tzinfo else fetched.replace(tzinfo=timezone.utc)) <= self.ttl
        except (TypeError, ValueError): return False
    @staticmethod
    def _response(payload: dict[str, Any], status: str, is_cached: bool, warning: str | None, limit: int) -> dict[str, Any]:
        return {"symbol": payload["symbol"], "provider_symbol": payload["provider_symbol"], "items": payload["items"][:limit], "source_status": status, "fetched_at": payload["fetched_at"], "is_cached": is_cached, "warning": warning, "dropped_unapproved_sources": payload.get("dropped_unapproved_sources", []), "source_warnings": payload.get("source_warnings", [])}

    def get(self, code: str, *, limit: int = 20, refresh: bool = False) -> dict[str, Any]:
        if not 1 <= limit <= 100: raise NewsError("limit 必须介于 1 到 100")
        normalized_code, symbol = code.strip().upper(), provider_symbol(code)
        cached = self._read_cache(normalized_code)
        if cached and not refresh and self._fresh(cached): return self._response(cached, "CACHED", True, None, limit)
        rows: list[dict[str, Any]] = []; warnings: list[str] = []; errors: list[Exception] = []
        try: rows.extend(self.provider.company_news(symbol, max(100, limit)))
        except Exception as error: errors.append(error)
        fetch_market = getattr(self.provider, "market_news", None)
        if callable(fetch_market):
            try: market_rows, market_warnings = fetch_market(max(100, limit)); rows.extend(market_rows); warnings.extend(market_warnings)
            except Exception as error: errors.append(error)
        if not rows and errors:
            if cached: return self._response(cached, "STALE_CACHE", True, "新闻源暂时不可用，正在展示最近缓存数据。", limit)
            return {"symbol": normalized_code, "provider_symbol": symbol, "items": [], "source_status": "UNAVAILABLE", "fetched_at": None, "is_cached": False, "warning": f"新闻源暂时不可用：{str(errors[0]) or '请稍后重试'}", "dropped_unapproved_sources": [], "source_warnings": warnings}
        approved: list[dict[str, Any]] = []; dropped: set[str] = set(); allowed = {source.source_id for source in self.sources}
        for item in normalize_records(rows, normalized_code):
            source = resolve_source(item["source"])
            if not source or source.source_id not in allowed: dropped.add(item["source"]); continue
            item.update(source_id=source.source_id, source=source.display_name, license_status=source.authorization, allow_summary=source.allow_summary, scope=source.scope)
            item["summary"] = item["summary"] if source.allow_summary else None; item["analysis"] = self.analyzer.analyze(item["title"], item["summary"]); approved.append(item)
        payload = {"symbol": normalized_code, "provider_symbol": symbol, "fetched_at": self._now().isoformat(), "items": approved, "dropped_unapproved_sources": sorted(dropped), "source_warnings": warnings}
        self._write_cache(normalized_code, payload); self._write_history(normalized_code, payload)
        return self._response(payload, "LIVE" if approved else "NO_DATA", False, "；".join(warnings) if warnings else (None if approved else "当前数据源未返回该标的新闻。"), limit)

    def insight(self, code: str, *, as_of: str | None = None) -> dict[str, Any]:
        normalized_code, cached = code.strip().upper(), self._read_cache(code.strip().upper())
        if as_of:
            if not cached: return {"status": "UNAVAILABLE", "reason": "该历史日期没有已保存的新闻快照。", "citations": []}
            if pd.Timestamp(cached["fetched_at"]) > pd.Timestamp(as_of).tz_localize("America/New_York") + pd.Timedelta(hours=16): return {"status": "UNAVAILABLE", "reason": "新闻快照晚于该交易日收盘，不能用于历史决策。", "citations": []}
        elif not cached:
            if self._now().astimezone(ZoneInfo("America/New_York")).hour < 16: return {"status": "UNAVAILABLE", "reason": "收盘后才自动更新新闻情绪；可在新闻中心手动刷新。", "citations": []}
            self.get(normalized_code, limit=100); cached = self._read_cache(normalized_code)
        if not cached or not cached.get("items"): return {"status": "UNAVAILABLE", "reason": "没有来自已授权白名单来源的可用新闻。", "citations": []}
        company: list[dict[str, Any]] = []; market: list[dict[str, Any]] = []
        for item in cached["items"]:
            citation = {key: item.get(key) for key in ("id", "source_id", "source", "title", "published_at", "url", "license_status", "scope")} | {"analysis": item.get("analysis") or self.analyzer.analyze(item["title"], item.get("summary"))}
            (market if item.get("scope") == "MARKET" else company).append(citation)
        def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
            dated = [item for item in items if item.get("published_at")]; source_count = len({item["source_id"] for item in items})
            if not dated: return {"status": "UNAVAILABLE", "reason": "没有带发布时间的新闻，不能用于严格时序判断。", "article_count": len(items), "source_count": source_count}
            values = [float(item["analysis"]["sentiment_score"]) * freshness_weight(max(0, (pd.Timestamp(self._now()) - pd.Timestamp(item["published_at"])).total_seconds() / 3600)) for item in dated]
            score, sources = sum(values) / len(values), {item["source_id"] for item in dated}
            return {"status": "AVAILABLE", "direction": "BULLISH" if score >= .15 else "BEARISH" if score <= -.15 else "NEUTRAL", "score": round(score, 4), "confidence": round(min(.90, .25 + .12 * len(dated) + .10 * max(0, len(sources) - 1)), 4), "article_count": len(dated), "source_count": len(sources), "confirmation_eligible": len(sources) >= 2}
        company_summary, market_summary = summarize(company), summarize(market)
        high_risk = [item for item in company if item["published_at"] and item["analysis"]["high_impact"] and item["analysis"]["direction"] == "BEARISH"]
        available = company_summary["status"] == "AVAILABLE" or market_summary["status"] == "AVAILABLE"
        return {"status": "AVAILABLE" if available else "UNAVAILABLE", "company": company_summary, "market": market_summary, "high_risk": high_risk, "citations": company[:5] + market[:5], "source_warnings": cached.get("source_warnings", [])}
