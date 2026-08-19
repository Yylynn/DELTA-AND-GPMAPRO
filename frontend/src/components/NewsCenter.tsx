import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { MarketCodeInput } from "@/components/MarketCodeInput";
import { resolveMarketCode, type Market } from "@/lib/marketCode";

type NewsItem = {
  id: string;
  symbol: string;
  title: string;
  url: string | null;
  source: string;
  published_at: string | null;
  summary: string | null;
  scope?: "COMPANY" | "MARKET";
};

type NewsResponse = {
  symbol: string;
  provider_symbol: string;
  items: NewsItem[];
  source_status: "LIVE" | "CACHED" | "STALE_CACHE" | "NO_DATA" | "UNAVAILABLE" | "DISABLED";
  fetched_at: string | null;
  is_cached: boolean;
  warning: string | null;
  dropped_unapproved_sources?: string[];
  source_warnings?: string[];
};
type NewsSource = { source_id: string; display_name: string; authorization: string; enabled: boolean; kind: string; collector: string; scope: string };

async function fetchNews(code: string, refresh: boolean): Promise<NewsResponse> {
  const params = new URLSearchParams({ limit: "20", refresh: String(refresh) });
  const response = await fetch(`/api/news/${encodeURIComponent(code)}?${params}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function formatTime(value: string | null) {
  if (!value) return "发布时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

const statusText: Record<NewsResponse["source_status"], string> = {
  LIVE: "实时获取",
  CACHED: "缓存数据",
  STALE_CACHE: "历史缓存",
  NO_DATA: "暂无新闻",
  UNAVAILABLE: "数据源不可用",
  DISABLED: "功能已关闭",
};

export function NewsCenter() {
  const [symbol, setSymbol] = useState("AAPL");
  const [market, setMarket] = useState<Market>("US");
  const [refresh, setRefresh] = useState(false);
  const [submitted, setSubmitted] = useState("US.AAPL");
  const code = useMemo(() => { try { return resolveMarketCode(symbol, market); } catch { return ""; } }, [symbol, market]);
  const query = useQuery<NewsResponse>({
    queryKey: ["news", submitted, refresh],
    queryFn: () => fetchNews(submitted, refresh),
    enabled: Boolean(submitted),
    retry: false,
  });
  const sources = useQuery<{ sources: NewsSource[] }>({ queryKey: ["news-sources"], queryFn: async () => { const response = await fetch("/api/news/sources"); if (!response.ok) throw new Error(await response.text()); return response.json(); }, retry: false });
  const load = (force = false) => {
    if (!code) return;
    setRefresh(force);
    setSubmitted(code);
    if (code === submitted && force === refresh) void query.refetch();
  };
  const data = query.data;

  return <div className="terminal-page">
    <div className="page-heading">
      <div><h1>新闻中心</h1><p>只读新闻证据：公司新闻与市场新闻分开保存；只保留来源、标题、时间和原文链接。</p></div>
      <form className="flex gap-2" onSubmit={event => { event.preventDefault(); load(false); }}>
        <MarketCodeInput market={market} value={symbol} onMarketChange={setMarket} onValueChange={setSymbol} className="w-28" />
        <button className="secondary-button" type="submit" disabled={!code || query.isFetching}>查询</button>
        <button className="primary-button flex items-center gap-1" type="button" onClick={() => load(true)} disabled={!code || query.isFetching}><RefreshCw size={14} className={query.isFetching ? "animate-spin" : ""} />刷新新闻</button>
      </form>
    </div>
    {query.isError && <p className="error-banner">{query.error instanceof Error ? query.error.message : "新闻查询失败。"}</p>}
    <section className="panel p-4">
      <div className="grid grid-cols-4 gap-3 text-sm">
        <div><span>终端代码</span><b>{data?.symbol ?? submitted}</b></div>
        <div><span>新闻代码</span><b>{data?.provider_symbol ?? "—"}</b></div>
        <div><span>数据状态</span><b>{data ? statusText[data.source_status] : query.isFetching ? "加载中…" : "—"}</b></div>
        <div><span>更新时间</span><b>{formatTime(data?.fetched_at ?? null)}</b></div>
      </div>
      {data?.warning && <p className="news-warning">{data.warning}</p>}
      {data?.source_warnings?.map(warning => <p key={warning} className="news-warning">{warning}</p>)}
      {data?.dropped_unapproved_sources?.length ? <p className="news-warning">未纳入情绪/建议的非白名单来源：{data.dropped_unapproved_sources.join("、")}</p> : null}
    </section>
    <section className="panel mt-4 p-4"><div className="panel-title">新闻来源白名单</div><div className="source-grid">{sources.data?.sources.map(source => <div key={source.source_id}><b>{source.display_name}</b><span>{source.enabled ? `${source.collector === "RSS" ? "已配置 RSS" : "已接入"} · ${source.scope === "MARKET" ? "市场新闻" : "公司新闻"}` : source.authorization === "LICENSE_REQUIRED" ? "需授权" : "待配置 RSS/API"}</span></div>)}</div></section>
    <section className="panel mt-4 overflow-hidden">
      <div className="news-list-title"><span>最近新闻</span><span>{data?.items.length ?? 0} 条</span></div>
      {query.isLoading ? <p className="muted p-4">正在获取新闻…</p> : !data?.items.length ? <p className="muted p-4">暂无可展示的新闻。</p> : <div className="news-list">
        {data.items.map(item => <article className="news-item" key={item.id}>
          <div className="news-item-meta"><span>{item.source} · {item.scope === "MARKET" ? "市场" : "公司"}</span><span>{formatTime(item.published_at)}</span></div>
          <div className="news-item-title">{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}<ExternalLink size={13} /></a> : item.title}</div>
          {item.summary && <p>{item.summary}</p>}
        </article>)}
      </div>}
    </section>
  </div>;
}
