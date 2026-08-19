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


# RSS entries retain titles, links and dates only. No article body is fetched.
SOURCES = (
    NewsSource("cnbc", "CNBC", ("US", "GLOBAL"), "财经媒体", 0, "PUBLIC_RSS", True, False, ("cnbc",), "RSS", "MARKET", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    NewsSource("reuters", "Reuters", ("US", "GLOBAL"), "通讯社", 0, "LICENSE_REQUIRED", aliases=("reuters", "路透")),
    NewsSource("bloomberg", "Bloomberg", ("US", "GLOBAL"), "财经媒体", 0, "LICENSE_REQUIRED", aliases=("bloomberg", "彭博")),
    NewsSource("eastmoney", "东方财富", ("CN",), "财经门户", 1, "PUBLIC_RSS_OR_API", aliases=("东方财富", "eastmoney")),
    NewsSource("wallstreetcn", "华尔街见闻", ("CN", "GLOBAL"), "宏观资讯", 1, "PUBLIC_RSS_OR_API", aliases=("华尔街见闻", "wallstreetcn")),
    NewsSource("marketwatch", "MarketWatch", ("US",), "财经媒体", 1, "PUBLIC_RSS", True, False, ("marketwatch",), "RSS", "MARKET", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    NewsSource("simuwang", "私募排排网", ("CN",), "基金数据", 2, "LICENSE_REQUIRED", aliases=("私募排排网",)),
    NewsSource("stcn", "证券时报", ("CN",), "证券媒体", 1, "PUBLIC_RSS_OR_API", aliases=("证券时报", "stcn")),
    NewsSource("10jqka", "同花顺财经", ("CN",), "财经门户", 1, "PUBLIC_RSS_OR_API", aliases=("同花顺", "10jqka")),
    NewsSource("xueqiu", "雪球", ("CN", "US"), "投资者社区", 2, "PUBLIC_RSS_OR_API", aliases=("雪球", "xueqiu")),
    NewsSource("thestreet", "TheStreet", ("US",), "美股分析", 1, "OPENBB_PUBLIC", True, False, ("thestreet", "the street"), "OPENBB", "COMPANY"),
    NewsSource("barclayhedge", "BarclayHedge/对冲数据", ("GLOBAL",), "对冲基金数据", 2, "LICENSE_REQUIRED", aliases=("barclayhedge", "巴克莱对冲")),
    NewsSource("bridgewater", "桥水观察", ("GLOBAL",), "策略观察", 2, "LICENSE_REQUIRED", aliases=("桥水", "bridgewater")),
    NewsSource("morningstar", "晨星", ("US", "GLOBAL"), "基金评级", 1, "LICENSE_REQUIRED", aliases=("morningstar", "晨星")),
    NewsSource("jiemian", "界面新闻", ("CN",), "财经商业新闻", 1, "PUBLIC_RSS_OR_API", aliases=("界面新闻", "jiemian")),
)


def resolve_source(value: str) -> NewsSource | None:
    normalized = value.strip().casefold()
    return next((item for item in SOURCES if normalized == item.display_name.casefold() or normalized in item.aliases), None)


def enabled_sources(*, cnbc: bool = True, marketwatch: bool = True) -> tuple[NewsSource, ...]:
    switches = {"cnbc": cnbc, "marketwatch": marketwatch}
    return tuple(source for source in SOURCES if source.enabled and switches.get(source.source_id, True))


def source_catalog(*, cnbc: bool = True, marketwatch: bool = True) -> list[dict]:
    switches = {"cnbc": cnbc, "marketwatch": marketwatch}
    return [{**asdict(item), "markets": list(item.markets), "aliases": list(item.aliases), "enabled": item.enabled and switches.get(item.source_id, True)} for item in SOURCES]
