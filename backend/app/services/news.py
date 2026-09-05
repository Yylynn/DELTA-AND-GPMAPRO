"""Read-only, traceable company and market news with a local cache."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha1
import json
from pathlib import Path
import re
from threading import Lock
import time
from typing import Any, Callable, Protocol
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.config.news_sources import NewsSource, enabled_sources, resolve_source
from app.config.news_universe import entity_terms
from app.services.news_analysis import NewsAnalyzer, freshness_weight
from app.services.trading_calendar import earliest_trade_at


MARKET_HEADLINE_SOURCES = (
    {"id": "all", "label": "全部头条", "source_ids": ("wallstreetcn", "cnbc", "marketwatch", "fed_press", "treasury_press", "coindesk", "cointelegraph", "decrypt", "theblock")},
    {"id": "wallstreetcn", "label": "华尔街见闻", "source_ids": ("wallstreetcn",)},
    {"id": "cnbc", "label": "CNBC", "source_ids": ("cnbc",)},
    {"id": "marketwatch", "label": "MarketWatch", "source_ids": ("marketwatch",)},
    {"id": "official", "label": "官方发布", "source_ids": ("fed_press", "treasury_press")},
    {"id": "coindesk", "label": "CoinDesk", "source_ids": ("coindesk",)},
    {"id": "crypto", "label": "加密资讯", "source_ids": ("cointelegraph", "decrypt", "theblock")},
)


def _published_key(item: dict[str, Any]) -> str:
    return str(item.get("published_at") or "")


def build_market_headlines(items: list[dict[str, Any]], health: list[dict[str, Any]]) -> dict[str, Any]:
    """Build stable source tabs and a source-diverse combined headline order."""
    ordered = sorted(items, key=_published_key, reverse=True)
    health_by_id = {str(item.get("source_id")): item for item in health}
    groups = []
    for definition in MARKET_HEADLINE_SOURCES:
        source_ids = tuple(definition["source_ids"])
        matching = [item for item in ordered if item.get("source_id") in source_ids]
        if definition["id"] == "all" and matching:
            picked, seen_ids = [matching[0]], {matching[0].get("id")}
            latest_by_source = []
            for source_id in source_ids:
                if source_id == matching[0].get("source_id"): continue
                candidate = next((item for item in matching if item.get("source_id") == source_id and item.get("id") not in seen_ids), None)
                if candidate: latest_by_source.append(candidate)
            for item in sorted(latest_by_source, key=_published_key, reverse=True):
                if len(picked) >= 5: break
                picked.append(item); seen_ids.add(item.get("id"))
            matching = picked + [item for item in matching if item.get("id") not in seen_ids]
        available = bool(matching) or any(health_by_id.get(source_id, {}).get("availability") == "AVAILABLE" for source_id in source_ids)
        groups.append({"id": definition["id"], "label": definition["label"], "source_ids": list(source_ids), "available": available, "count": len(matching), "items": matching})
    return {"source_order": [item["id"] for item in MARKET_HEADLINE_SOURCES], "headline_groups": groups}


class NewsProvider(Protocol):
    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]: ...


class OpenBBNewsProvider:
    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        try:
            from openbb import obb
            result = obb.news.company(symbol=symbol, limit=limit)
            raw_items = result.results
            provider_name = result.provider or "yfinance"
        except Exception:
            raw_items = []
            provider_name = "yfinance"
        rows = []
        for item in raw_items:
            raw = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            rows.append({
                "id": raw.get("id"), "title": raw.get("title"), "url": raw.get("url"),
                "date": raw.get("date"), "summary": raw.get("summary") or raw.get("excerpt"),
                "publisher": raw.get("source") or "Unknown publisher", "provider": provider_name,
                "scope": "COMPANY", "source_id": "openbb_yfinance", "entity_tickers": [symbol.upper()],
            })
        if rows:
            return rows
        # OpenBB's yfinance adapter sometimes reports an Empty error although the
        # underlying yfinance feed is available.  Keep this within the approved
        # OpenBB/yfinance source rather than silently substituting a new vendor.
        try:
            import yfinance as yf
            raw_news = yf.Ticker(symbol).news or []
        except Exception as error:
            raise RuntimeError(f"OpenBB/yfinance 均未返回数据：{error}") from error
        for item in raw_news[:limit]:
            content = item.get("content", item) if isinstance(item, dict) else {}
            if not isinstance(content, dict):
                continue
            rows.append({
                "id": content.get("id") or item.get("id"), "title": content.get("title") or item.get("title"),
                "url": content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("url") or item.get("link"),
                "date": content.get("pubDate") or content.get("displayTime") or item.get("providerPublishTime"),
                "summary": content.get("summary") or item.get("summary"),
                "publisher": (content.get("provider") or {}).get("displayName") if isinstance(content.get("provider"), dict) else content.get("publisher") or "yfinance",
                "provider": "yfinance", "scope": "COMPANY", "source_id": "openbb_yfinance", "entity_tickers": [symbol.upper()],
            })
        return rows


class FinnhubCompanyNewsProvider:
    def __init__(self, api_key: str, timeout_seconds: float = 8) -> None:
        self.api_key, self.timeout_seconds = api_key.strip(), timeout_seconds

    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("未配置 DELTA_FINNHUB_API_KEY")
        end = datetime.now(timezone.utc).date(); start = end - timedelta(days=30)
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get("https://finnhub.io/api/v1/company-news", params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": self.api_key})
            response.raise_for_status(); payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("返回格式不是新闻列表")
        return [{"id": row.get("id"), "title": row.get("headline"), "url": row.get("url"),
                 "date": datetime.fromtimestamp(int(row["datetime"]), timezone.utc).isoformat() if row.get("datetime") else None,
                 "summary": row.get("summary"), "publisher": "Finnhub Company News", "provider": "finnhub",
                 "source_id": "finnhub_company", "scope": "COMPANY", "entity_tickers": [symbol.upper()],
                 "image": row.get("image")} for row in payload[:limit]]


class SecEdgarNewsProvider:
    FORMS = {"8-K": "OPERATING", "10-Q": "EARNINGS", "10-K": "EARNINGS", "4": "OTHER"}

    def __init__(self, user_agent: str, timeout_seconds: float = 8) -> None:
        self.user_agent, self.timeout_seconds, self._tickers = user_agent, timeout_seconds, None

    def _cik(self, client: httpx.Client, symbol: str) -> int | None:
        if self._tickers is None:
            response = client.get("https://www.sec.gov/files/company_tickers.json"); response.raise_for_status()
            self._tickers = {str(row["ticker"]).upper(): int(row["cik_str"]) for row in response.json().values()}
        return self._tickers.get(symbol.upper())

    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        payload = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
                    cik = self._cik(client, symbol)
                    if cik is None: return []
                    response = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"); response.raise_for_status(); payload = response.json()
                break
            except httpx.HTTPError as error:
                last_error = error
                if attempt < 2: time.sleep(.25 * (attempt + 1))
        if payload is None:
            raise RuntimeError(f"SEC 请求失败：{last_error}") from last_error
        recent = payload.get("filings", {}).get("recent", {}); rows = []; form4_count = 0
        for index, form in enumerate(recent.get("form", [])):
            base_form = str(form).removesuffix("/A")
            if base_form not in self.FORMS: continue
            if base_form == "4":
                if form4_count >= min(10, max(2, limit // 4)): continue
                form4_count += 1
            accession = recent["accessionNumber"][index]; document = recent["primaryDocument"][index]
            accepted = recent.get("acceptanceDateTime", [None] * (index + 1))[index]
            if accepted:
                stamp = pd.Timestamp(accepted)
                if stamp.tzinfo is None: stamp = stamp.tz_localize("America/New_York")
                accepted = stamp.isoformat()
            rows.append({"id": accession, "title": f"{symbol.upper()} {form} SEC filing", "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}",
                         "date": accepted or recent.get("filingDate", [None] * (index + 1))[index], "available_at": accepted,
                         "summary": f"SEC form {form}", "publisher": "SEC EDGAR", "provider": "sec",
                         "source_id": "sec_edgar", "scope": "COMPANY", "entity_tickers": [symbol.upper()],
                         "event_type_hint": self.FORMS[base_form]})
            if len(rows) >= limit: break
        return rows


class PublicRssNewsProvider:
    """Fetch only publisher-provided RSS metadata; article pages are never fetched."""
    def __init__(self, sources: tuple[NewsSource, ...], timeout_seconds: float = 15, health: Callable[..., None] | None = None) -> None:
        self.sources = tuple(item for item in sources if item.collector == "RSS" and item.rss_url)
        self.timeout_seconds = max(2, min(timeout_seconds, 8))
        self.health = health or (lambda **_: None)

    @staticmethod
    def _text(item: ElementTree.Element, *names: str) -> str | None:
        for name in names:
            found = item.find(name)
            if found is not None and found.text:
                return found.text.strip()
        return None

    @staticmethod
    def _image(item: ElementTree.Element) -> str | None:
        """Read publisher-provided RSS media only; never visit article pages."""
        names = (
            "{http://search.yahoo.com/mrss/}thumbnail",
            "{http://search.yahoo.com/mrss/}content",
            "enclosure",
        )
        for name in names:
            node = item.find(name)
            if node is None: continue
            url = str(node.attrib.get("url") or "").strip()
            media_type = str(node.attrib.get("type") or "")
            if url and (name != "enclosure" or not media_type or media_type.startswith("image/")):
                return url
        return None

    def _fetch_one(self, source: NewsSource, limit: int) -> tuple[list[dict[str, Any]], str | None]:
        error_text = None
        for attempt in range(3):
            try:
                timeout = httpx.Timeout(self.timeout_seconds, connect=min(4, self.timeout_seconds))
                with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; DELTA-NewsCenter/1.0)", "Accept": "application/rss+xml, application/xml, text/xml, */*"}) as client:
                    response = client.get(str(source.rss_url))
                    response.raise_for_status()
                    root = ElementTree.fromstring(response.content)
                rows = []
                for item in root.findall(".//item")[:limit]:
                    title = self._text(item, "title")
                    if title:
                        rows.append({"title": title, "url": self._text(item, "link"), "date": self._text(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date"), "summary": self._text(item, "description", "{http://purl.org/rss/1.0/modules/content/}encoded"), "image": self._image(item), "publisher": source.display_name, "provider": "rss", "source": source.display_name, "source_id": source.source_id, "scope": "MARKET"})
                self.health(source_id=source.source_id, status="OK", error=None)
                return rows, None
            except (httpx.HTTPError, ElementTree.ParseError, ValueError) as error:
                error_text = str(error) or type(error).__name__
                if attempt < 2:
                    time.sleep(.2 * (attempt + 1))
        self.health(source_id=source.source_id, status="DEGRADED", error=error_text)
        return [], f"{source.display_name} RSS 暂时不可用：{error_text}"

    def market_news(self, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.sources))) as pool:
            futures = {pool.submit(self._fetch_one, source, limit): source for source in self.sources}
            for future in as_completed(futures):
                try:
                    found, warning = future.result(); rows.extend(found)
                    if warning: warnings.append(warning)
                except Exception as error:  # pragma: no cover - executor guard
                    source = futures[future]; self.health(source_id=source.source_id, status="DEGRADED", error=str(error))
                    warnings.append(f"{source.display_name} RSS 暂时不可用：{error}")
        return rows, warnings


class DefaultNewsProvider:
    def __init__(self, sources: tuple[NewsSource, ...], timeout_seconds: float = 15, health: Callable[..., None] | None = None, *, finnhub_api_key: str = "", sec_user_agent: str = "") -> None:
        self.rss = PublicRssNewsProvider(sources, timeout_seconds, health); self.health = health or (lambda **_: None)
        configured = {source.source_id for source in sources}
        candidates = [("openbb_yfinance", OpenBBNewsProvider())]
        if "sec_edgar" in configured: candidates.append(("sec_edgar", SecEdgarNewsProvider(sec_user_agent, timeout_seconds)))
        if "finnhub_company" in configured and finnhub_api_key.strip(): candidates.append(("finnhub_company", FinnhubCompanyNewsProvider(finnhub_api_key, timeout_seconds)))
        elif "finnhub_company" in configured:
            self.health(source_id="finnhub_company", status="NOT_CONFIGURED", error="未配置 DELTA_FINNHUB_API_KEY；该备用源不会参与本次抓取。")
        self.company_providers = [(key, provider) for key, provider in candidates if key in configured]

    def company_news(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.company_providers))) as pool:
            futures = {pool.submit(provider.company_news, symbol, limit): source_id for source_id, provider in self.company_providers}
            for future in as_completed(futures):
                source_id = futures[future]
                try:
                    found = future.result()
                    rows.extend(found)
                    self.health(source_id=source_id, status="OK" if found else "NO_DATA", error=None if found else "未返回近期公司新闻。")
                except Exception as error:
                    self.health(source_id=source_id, status="DEGRADED", error=str(error) or type(error).__name__)
        return rows

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
        stamp = pd.Timestamp(value, unit="s") if isinstance(value, (int, float)) else pd.Timestamp(value)
        return (stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp).isoformat()
    except (TypeError, ValueError): return None


def normalize_records(rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        title = str(row.get("title") or row.get("headline") or "").strip()
        if not title: continue
        url = str(row.get("url") or row.get("link") or "").strip() or None
        published_at = _timestamp(row.get("date") or row.get("published_at") or row.get("published"))
        publisher = str(row.get("publisher") or row.get("source") or "Unknown publisher").strip() or "Unknown publisher"
        provider = str(row.get("provider") or ("rss" if row.get("scope") == "MARKET" else "yfinance")).strip()
        identity = f"{publisher}|{url or title}|{published_at or ''}"
        deduped.setdefault(identity, {"id": str(row.get("id") or sha1(identity.encode()).hexdigest()[:16]), "symbol": symbol, "title": title, "url": url, "publisher": publisher, "provider": provider, "source_id": row.get("source_id"), "published_at": published_at, "available_at": _timestamp(row.get("available_at")) or published_at, "summary": str(row.get("summary") or row.get("description") or row.get("text") or "").strip() or None, "scope": row.get("scope", "COMPANY"), "entity_tickers": row.get("entity_tickers", []), "event_type_hint": row.get("event_type_hint"), "thumbnail": row.get("image")})
    return sorted(deduped.values(), key=lambda item: item["published_at"] or "", reverse=True)


class NewsService:
    def __init__(self, cache_dir: Path, ttl_seconds: int = 900, provider: NewsProvider | None = None, now: Callable[[], datetime] | None = None, *, sources: tuple[NewsSource, ...] | None = None, rss_timeout_seconds: float = 15, finnhub_api_key: str = "", sec_user_agent: str = "DELTA-Research-Terminal/0.1 research@example.invalid", zh_sentiment_enabled: bool = True) -> None:
        self.cache_dir, self.ttl = cache_dir, timedelta(seconds=max(0, ttl_seconds))
        self.sources = sources or enabled_sources()
        self.health: dict[str, dict[str, Any]] = {
            source.source_id: {
                "source_id": source.source_id, "display_name": source.display_name,
                "scope": source.scope, "collector": source.collector,
                "status": "UNKNOWN", "availability": "NOT_CHECKED",
                "availability_reason": "尚未在本进程中检查该来源。",
                "last_success_at": None, "last_error": None, "consecutive_failures": 0,
            }
            for source in self.sources
        }
        self.provider = provider or DefaultNewsProvider(self.sources, rss_timeout_seconds, self._mark_health, finnhub_api_key=finnhub_api_key, sec_user_agent=sec_user_agent)
        self._now, self.analyzer = now or (lambda: datetime.now(timezone.utc)), NewsAnalyzer(enable_zh=zh_sentiment_enabled)
        self._market_refresh_lock = Lock()
        self._last_market_refresh_monotonic = float("-inf")

    def _mark_health(self, *, source_id: str, status: str, error: str | None) -> None:
        item = self.health.setdefault(source_id, {"source_id": source_id, "display_name": source_id, "status": "UNKNOWN", "availability": "NOT_CHECKED", "availability_reason": "尚未检查。", "last_success_at": None, "last_error": None, "consecutive_failures": 0})
        item["status"] = status
        if status == "OK": item.update(availability="AVAILABLE", availability_reason=None, last_success_at=self._now().isoformat(), last_error=None, consecutive_failures=0)
        elif status == "NO_DATA": item.update(availability="NO_DATA", availability_reason=error or "未返回近期新闻。", last_error=None, consecutive_failures=0)
        elif status == "NOT_CONFIGURED": item.update(availability="NOT_CONFIGURED", availability_reason=error or "来源尚未配置。", last_error=None, consecutive_failures=0)
        else: item.update(availability="UNAVAILABLE", availability_reason=error or "来源未返回可用响应。", last_error=error, consecutive_failures=int(item.get("consecutive_failures", 0)) + 1)

    def source_health(self) -> list[dict[str, Any]]:
        return [self.health[source.source_id].copy() for source in self.sources]

    def _path(self, code: str) -> Path: return self.cache_dir / f"{code.replace('.', '_')}.json"
    def _market_path(self) -> Path: return self.cache_dir / "MARKET.json"
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
    def _market_response(self, payload: dict[str, Any], status: str, is_cached: bool, warning: str | None, limit: int) -> dict[str, Any]:
        market_items = payload.get("market_items", [])[:limit]
        headlines = build_market_headlines(market_items, self.source_health())
        return {"market_items": market_items, "source_status": status,
                "fetched_at": payload.get("fetched_at"), "is_cached": is_cached, "warning": warning,
                "source_warnings": payload.get("source_warnings", []), "source_health": self.source_health(), **headlines}

    def get_market(self, *, limit: int = 20, refresh: bool = False) -> dict[str, Any]:
        """Read the global macro stream without coupling it to a selected ticker."""
        if not 1 <= limit <= 100: raise NewsError("limit 必须介于 1 到 100")
        try:
            cached = json.loads(self._market_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if cached and cached.get("fetched_at") and not refresh and self._fresh(cached):
            return self._market_response(cached, "CACHED", True, None, limit)
        observed_fetched_at = cached.get("fetched_at") if cached else None
        with self._market_refresh_lock:
            try: current = json.loads(self._market_path().read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): current = None
            if current and current.get("fetched_at") != observed_fetched_at:
                return self._market_response(current, "CACHED", True, None, limit)
            if current and refresh and time.monotonic() - self._last_market_refresh_monotonic < 5:
                return self._market_response(current, "CACHED", True, None, limit)
            if current and not refresh and self._fresh(current):
                return self._market_response(current, "CACHED", True, None, limit)
            try:
                rows, warnings = self.provider.market_news(max(100, limit))
            except Exception as error:
                fallback = current or cached
                if fallback: return self._market_response(fallback, "STALE_CACHE", True, "宏观新闻源暂时不可用，正在展示最近缓存数据。", limit)
                return self._market_response({}, "UNAVAILABLE", False, f"宏观新闻源暂时不可用：{error}", limit)
            if not rows and (current or cached):
                fallback = current or cached
                warning = "；".join(warnings) or "全部宏观新闻源本次均未返回数据。"
                return self._market_response(fallback, "STALE_CACHE", True, f"{warning} 正在展示最近缓存数据。", limit)
            items: list[dict[str, Any]] = []
            allowed = {source.source_id for source in self.sources}
            for item in normalize_records(rows, "MARKET"):
                source = next((candidate for candidate in self.sources if candidate.source_id == item.get("source_id")), None) or resolve_source(item["publisher"])
                if not source or source.source_id not in allowed or source.scope != "MARKET": continue
                raw_summary = item["summary"]
                item.update(source_id=source.source_id, source=source.display_name, license_status=source.authorization, allowed_fields=list(source.allowed_fields), allow_summary=source.allow_summary, entity_status="ACCEPTED", entity_matches=[], scope="MARKET")
                item["summary"] = raw_summary if source.allow_summary else None
                item["analysis"] = self.analyzer.analyze(item["title"], raw_summary, item.get("event_type_hint"))
                item["language"] = item["analysis"]["language"]
                item["earliest_trade_at"] = None; item["factor_eligible"] = False
                items.append(item)
            payload = {"fetched_at": self._now().isoformat(), "market_items": items, "source_warnings": warnings}
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._market_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._last_market_refresh_monotonic = time.monotonic()
            return self._market_response(payload, "LIVE" if items else "NO_DATA", False, "；".join(warnings) if warnings else None, limit)
    def _response(self, payload: dict[str, Any], status: str, is_cached: bool, warning: str | None, limit: int) -> dict[str, Any]:
        # `items` remains the company-only compatibility field used by factor snapshots.
        if "company_items" in payload:
            company_items = payload["company_items"]
            market_items = payload.get("market_items", [])
        else:
            # Never render legacy cached macro records as company news.
            legacy_items = payload.get("items", [])
            company_items = [item for item in legacy_items if item.get("scope") != "MARKET"]
            market_items = [item for item in legacy_items if item.get("scope") == "MARKET"]
        return {"symbol": payload["symbol"], "provider_symbol": payload["provider_symbol"], "items": company_items[:limit], "company_items": company_items[:limit], "market_items": market_items[:limit], "source_status": status, "fetched_at": payload["fetched_at"], "is_cached": is_cached, "warning": warning, "dropped_unapproved_sources": payload.get("dropped_unapproved_sources", []), "source_warnings": payload.get("source_warnings", []), "source_health": self.source_health()}

    def get(self, code: str, *, limit: int = 20, refresh: bool = False) -> dict[str, Any]:
        if not 1 <= limit <= 100: raise NewsError("limit 必须介于 1 到 100")
        normalized_code, symbol = code.strip().upper(), provider_symbol(code)
        cached = self._read_cache(normalized_code)
        if cached and not refresh and self._fresh(cached): return self._response(cached, "CACHED", True, None, limit)
        company_rows: list[dict[str, Any]] = []; market_rows: list[dict[str, Any]] = []
        warnings: list[str] = []; company_error: Exception | None = None; market_errors: list[Exception] = []
        try:
            company_rows = self.provider.company_news(symbol, max(100, limit))
            if not isinstance(self.provider, DefaultNewsProvider): self._mark_health(source_id="openbb_yfinance", status="OK", error=None)
        except Exception as error:
            company_error = error
            if not isinstance(self.provider, DefaultNewsProvider): self._mark_health(source_id="openbb_yfinance", status="DEGRADED", error=str(error))
        market_result = self.get_market(limit=max(100, limit), refresh=refresh)
        market_rows = market_result.get("market_items", [])
        warnings.extend(market_result.get("source_warnings", []))
        if market_result.get("source_status") == "UNAVAILABLE": market_errors.append(RuntimeError(market_result.get("warning") or "宏观新闻不可用"))
        if not company_rows and not market_rows and (company_error or market_errors):
            if cached: return self._response(cached, "STALE_CACHE", True, "新闻源暂时不可用，正在展示最近缓存数据。", limit)
            failure = company_error or market_errors[0]
            return {"symbol": normalized_code, "provider_symbol": symbol, "items": [], "company_items": [], "market_items": [], "source_status": "UNAVAILABLE", "fetched_at": None, "is_cached": False, "warning": f"新闻源暂时不可用：{str(failure) or '请稍后重试'}", "dropped_unapproved_sources": [], "source_warnings": warnings, "source_health": self.source_health()}
        company_items: list[dict[str, Any]] = []; market_items: list[dict[str, Any]] = []; dropped: set[str] = set(); allowed = {source.source_id for source in self.sources}
        for item in normalize_records(company_rows, normalized_code) + normalize_records(market_rows, normalized_code):
            source = next((candidate for candidate in self.sources if candidate.source_id == item.get("source_id")), None) or resolve_source(item["publisher"])
            if not source and item["scope"] == "COMPANY": source = next((candidate for candidate in self.sources if candidate.source_id == "openbb_yfinance"), None)
            if not source or source.source_id not in allowed:
                dropped.add(item["publisher"]); continue
            raw_summary = item["summary"]
            text = f"{item['title']} {raw_summary or ''}".casefold()
            terms = entity_terms(symbol) if item["scope"] == "COMPANY" else ()
            matched = [term for term in terms if re.search(rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])", text)]
            if symbol.upper() in {str(value).upper() for value in item.get("entity_tickers", [])} and symbol.casefold() not in matched: matched.append(symbol.casefold())
            item.update(source_id=source.source_id, source=source.display_name, license_status=source.authorization, allowed_fields=list(source.allowed_fields), allow_summary=source.allow_summary, entity_status="ACCEPTED" if item["scope"] == "MARKET" or matched else "REJECTED_ENTITY_MISMATCH", entity_matches=matched, scope=source.scope)
            item["summary"] = raw_summary if source.allow_summary else None
            item["analysis"] = self.analyzer.analyze(item["title"], raw_summary, item.get("event_type_hint"))
            item["language"] = item["analysis"]["language"]
            item["earliest_trade_at"] = earliest_trade_at(item["available_at"]) if item.get("available_at") and item["scope"] == "COMPANY" else None
            item["factor_eligible"] = bool(item["scope"] == "COMPANY" and matched and item["published_at"] and item["analysis"]["method"] == "FINBERT")
            if item["scope"] == "MARKET": market_items.append(item)
            elif item["entity_status"] == "ACCEPTED": company_items.append(item)
        payload = {"symbol": normalized_code, "provider_symbol": symbol, "fetched_at": self._now().isoformat(), "items": company_items, "company_items": company_items, "market_items": market_items, "dropped_unapproved_sources": sorted(dropped), "source_warnings": warnings}
        self._write_cache(normalized_code, payload); self._write_history(normalized_code, payload)
        company_health = [item for item in self.source_health() if item.get("scope") == "COMPANY"]
        all_company_unavailable = bool(company_health) and all(item.get("availability") in {"UNAVAILABLE", "NOT_CONFIGURED"} for item in company_health)
        if company_error:
            status, warning = "COMPANY_UNAVAILABLE", f"公司新闻源不可用：{str(company_error) or '请稍后重试'}。宏观新闻仅在下方“宏观新闻”区域展示，不会代替 {symbol} 的公司新闻。"
        elif all_company_unavailable:
            status, warning = "COMPANY_UNAVAILABLE", f"所有已配置公司新闻源当前均不可用；宏观新闻不会代替 {symbol} 的公司新闻。"
        elif not company_items:
            status, warning = "NO_COMPANY_NEWS", f"当前已授权公司新闻源未返回 {symbol} 的可验证公司新闻；下方宏观新闻不代表该标的。"
        else:
            status, warning = "LIVE", "；".join(warnings) if warnings else None
        return self._response(payload, status, False, warning, limit)

    def get_at(self, code: str, as_of: str, *, limit: int = 100) -> dict[str, Any]:
        """Read the latest immutable news snapshot known at a historical cutoff."""
        if not 1 <= limit <= 100:
            raise NewsError("limit 必须介于 1 到 100")
        normalized_code, symbol = code.strip().upper(), provider_symbol(code)
        try:
            cutoff = pd.Timestamp(as_of)
            if cutoff.tzinfo is None:
                if len(str(as_of).strip()) <= 10:
                    cutoff = cutoff + pd.Timedelta(hours=16)
                cutoff = cutoff.tz_localize("America/New_York")
            cutoff = cutoff.tz_convert("UTC")
        except (TypeError, ValueError):
            raise NewsError("as_of 必须是有效日期或带时区时间")
        folder = self.cache_dir.parent / "news_history" / normalized_code.replace(".", "_")
        selected: tuple[pd.Timestamp, dict[str, Any]] | None = None
        for path in folder.glob("*.json") if folder.exists() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                fetched = pd.Timestamp(payload["fetched_at"])
                if fetched.tzinfo is None:
                    fetched = fetched.tz_localize("UTC")
                fetched = fetched.tz_convert("UTC")
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if fetched <= cutoff and (selected is None or fetched > selected[0]):
                selected = (fetched, payload)
        if selected is None:
            return {"symbol": normalized_code, "provider_symbol": symbol, "items": [], "company_items": [], "market_items": [],
                    "source_status": "UNAVAILABLE", "fetched_at": None, "is_cached": False,
                    "warning": "该时间点之前没有已保存的新闻快照。", "dropped_unapproved_sources": [],
                    "source_warnings": [], "source_health": self.source_health()}
        return self._response(selected[1], "CACHED", True, "正在展示该时间点之前最后一份不可变新闻快照。", limit)

    def insight(self, code: str, *, as_of: str | None = None) -> dict[str, Any]:
        normalized_code, cached = code.strip().upper(), self._read_cache(code.strip().upper())
        if as_of:
            if not cached: return {"status": "UNAVAILABLE", "reason": "该历史日期没有已保存的新闻快照。", "citations": []}
            if pd.Timestamp(cached["fetched_at"]) > pd.Timestamp(as_of).tz_localize("America/New_York") + pd.Timedelta(hours=16): return {"status": "UNAVAILABLE", "reason": "新闻快照晚于该交易日收盘，不能用于历史决策。", "citations": []}
        elif not cached:
            if self._now().astimezone(ZoneInfo("America/New_York")).hour < 16: return {"status": "UNAVAILABLE", "reason": "收盘后才自动更新新闻情绪；可在新闻中心手动刷新。", "citations": []}
            self.get(normalized_code, limit=100); cached = self._read_cache(normalized_code)
        if not cached: return {"status": "UNAVAILABLE", "reason": "没有来自已授权白名单来源的可用新闻。", "citations": []}
        # New cache payloads keep company and market evidence independently.  The
        # legacy `items` fallback makes existing historical snapshots readable.
        cached_items = cached.get("company_items", cached.get("items", [])) + cached.get("market_items", [])
        if not cached_items: return {"status": "UNAVAILABLE", "reason": "没有来自已授权白名单来源的可用新闻。", "citations": []}
        company: list[dict[str, Any]] = []; market: list[dict[str, Any]] = []
        for item in cached_items:
            if item.get("scope") == "COMPANY" and item.get("entity_status") != "ACCEPTED":
                continue
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
