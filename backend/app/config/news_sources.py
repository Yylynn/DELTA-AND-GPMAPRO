"""Approved news-source registry and public collection configuration."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NewsSource:
    source_id: str
    display_name: str
    markets: tuple[str, ...]
    kind: str
    priority: int
    authorization: str
    enabled: bool = False
    allow_summary: bool = False
    aliases: tuple[str, ...] = ()
    collector: str = "NONE"
    scope: str = "COMPANY"
    rss_url: str | None = None
    refresh_minutes: int = 15
    # Metadata-only is the default for publisher RSS feeds.  The collector
    # never visits linked article pages or persists article bodies.
    allowed_fields: tuple[str, ...] = ("title", "url", "published_at", "thumbnail")


# RSS entries retain titles, links and dates only. No article body is fetched.
SOURCES = (
    NewsSource("cnbc", "CNBC", ("US", "GLOBAL"), "财经媒体", 0, "PUBLIC_RSS", True, False, ("cnbc",), "RSS", "MARKET", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    NewsSource("wallstreetcn", "华尔街见闻", ("CN", "GLOBAL"), "宏观资讯", 1, "PUBLIC_RSS", True, False, ("华尔街见闻", "wallstreetcn"), "RSS", "MARKET", "https://dedicated.wallstreetcn.com/rss.xml"),
    NewsSource("marketwatch", "MarketWatch", ("US",), "财经媒体", 1, "PUBLIC_RSS", True, False, ("marketwatch",), "RSS", "MARKET", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    NewsSource("fed_press", "Federal Reserve", ("US",), "官方发布", 0, "PUBLIC_RSS", True, True, ("federal reserve", "fed"), "RSS", "MARKET", "https://www.federalreserve.gov/feeds/press_all.xml"),
    NewsSource("treasury_press", "U.S. Treasury", ("US",), "官方发布", 0, "PUBLIC_RSS", True, True, ("treasury", "u.s. treasury"), "RSS", "MARKET", "https://home.treasury.gov/rss.xml"),
    NewsSource("coindesk", "CoinDesk", ("US", "GLOBAL"), "行业资讯", 2, "PUBLIC_RSS", True, False, ("coindesk",), "RSS", "MARKET", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    NewsSource("cointelegraph", "Cointelegraph", ("GLOBAL",), "加密资讯", 2, "PUBLIC_RSS", True, False, ("cointelegraph", "加密货币电报"), "RSS", "MARKET", "https://cointelegraph.com/rss"),
    NewsSource("decrypt", "Decrypt", ("GLOBAL",), "加密资讯", 2, "PUBLIC_RSS", True, False, ("decrypt",), "RSS", "MARKET", "https://decrypt.co/feed"),
    NewsSource("theblock", "The Block", ("GLOBAL",), "加密资讯", 2, "PUBLIC_RSS", True, False, ("the block", "theblock"), "RSS", "MARKET", "https://www.theblock.co/rss.xml"),
    # Kept disabled until the publisher's aggregation permission and endpoint
    # reliability are re-verified.  It remains visible in source diagnostics.
    NewsSource("chaincatcher", "ChainCatcher", ("CN", "GLOBAL"), "加密资讯", 2, "PENDING_APPROVAL", False, False, ("chaincatcher", "链捕手"), "RSS", "MARKET", "https://www.chaincatcher.com/rss.xml"),
    NewsSource("openbb_yfinance", "OpenBB/yfinance", ("US", "GLOBAL"), "新闻聚合", 1, "AGGREGATED_PUBLIC", True, False, ("openbb", "yfinance"), "OPENBB", "COMPANY"),
    NewsSource("sec_edgar", "SEC EDGAR", ("US",), "监管申报", 0, "PUBLIC_API", True, True, ("sec", "sec edgar"), "SEC", "COMPANY", refresh_minutes=30),
    NewsSource("finnhub_company", "Finnhub Company News", ("US",), "公司新闻", 1, "PUBLIC_API_KEY", True, True, ("finnhub", "finnhub company news"), "FINNHUB", "COMPANY"),
)


def resolve_source(value: str) -> NewsSource | None:
    normalized = value.strip().casefold()
    return next((item for item in SOURCES if normalized == item.display_name.casefold() or normalized in item.aliases), None)


def enabled_sources(*, cnbc: bool = True, marketwatch: bool = True) -> tuple[NewsSource, ...]:
    switches = {"cnbc": cnbc, "marketwatch": marketwatch}
    return tuple(source for source in SOURCES if source.enabled and switches.get(source.source_id, True))


def source_catalog(*, cnbc: bool = True, marketwatch: bool = True) -> list[dict]:
    switches = {"cnbc": cnbc, "marketwatch": marketwatch}
    return [{**asdict(item), "markets": list(item.markets), "aliases": list(item.aliases), "allowed_fields": list(item.allowed_fields), "enabled": item.enabled and switches.get(item.source_id, True)} for item in SOURCES]
