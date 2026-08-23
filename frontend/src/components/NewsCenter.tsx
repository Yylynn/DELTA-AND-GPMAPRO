import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { MarketCodeInput } from "@/components/MarketCodeInput";
import { MetricCard, PageHeader } from "@/components/ui/workspace";
import { resolveMarketCode, type Market } from "@/lib/marketCode";

type NewsItem = {
  id: string;
  symbol: string;
  title: string;
  url: string | null;
  source: string;
  published_at: string | null;
  summary: string | null;
  publisher?: string;
  entity_status?: "ACCEPTED" | "REJECTED_ENTITY_MISMATCH";
  factor_eligible?: boolean;
  scope?: "COMPANY" | "MARKET";
};

type SourceHealth = { source_id: string; display_name: string; scope: "COMPANY" | "MARKET"; collector: string; status: "OK" | "DEGRADED" | "UNKNOWN"; availability: "AVAILABLE" | "UNAVAILABLE" | "NOT_CHECKED"; availability_reason: string | null; last_success_at: string | null; last_error: string | null; consecutive_failures: number };
type Candidate = { symbol: string; tier: "FOCUS" | "WATCH" | "FILTERED"; research_state: "INSUFFICIENT_EVIDENCE" | "POSITIVE_WATCH" | "NEUTRAL" | "NEGATIVE_AVOID"; news_score: number; article_count: number; negative_catalyst: boolean; earliest_trade_at: string | null; validation_status: string; technical: { gpma_bullish: boolean; gpma_active_buy: boolean; delta_low_active: boolean }; evidence: Array<{ id: string; title: string; url: string | null; publisher: string; published_at: string; analysis: { direction: string; event_type: string } }> };
type CandidateResponse = { status: string; snapshot_at?: string; candidates: Candidate[]; market_risk_filter?: { status: string; score: number; source_count: number }; message: string };
type FactorEvaluation = { status: "VALIDATED" | "INSUFFICIENT_EVIDENCE"; sample_count: number; reason?: string; horizons: Array<{ horizon: number; status: string; sample_count: number; spearman_ic?: number; t_stat?: number; icir?: number; walk_forward?: { oos_sharpe_after_cost: number; test_count: number } }> };

type NewsResponse = {
  symbol: string;
  provider_symbol: string;
  items: NewsItem[];
  company_items: NewsItem[];
  market_items: NewsItem[];
  source_status: "LIVE" | "CACHED" | "STALE_CACHE" | "NO_DATA" | "NO_COMPANY_NEWS" | "COMPANY_UNAVAILABLE" | "UNAVAILABLE" | "DISABLED";
  fetched_at: string | null;
  is_cached: boolean;
  warning: string | null;
  dropped_unapproved_sources?: string[];
  source_warnings?: string[];
  source_health?: SourceHealth[];
};
type NewsSource = { source_id: string; display_name: string; authorization: string; enabled: boolean; kind: string; collector: string; scope: string };
type CompanyResearch = {
  symbol: string; coverage_status: "AVAILABLE" | "COVERAGE_GAP" | "SOURCE_UNAVAILABLE"; coverage_reason: string | null;
  assessment: "POSITIVE" | "NEGATIVE" | "NEUTRAL" | "INSUFFICIENT"; sentiment_score: number | null; confidence: number; coverage_score: number; historical_prediction_confidence: number | null; validation_status: string;
  supported_interpretation: string | null; unknowns: string[]; positive_catalysts: string[]; risk_items: string[];
  event_timeline: Array<{ id: string; title: string; source: string; published_at: string | null; url: string | null; event_type: string; direction: string; method: string }>;
  data_quality: { article_count: number; source_count: number; sources: string[]; earliest_published_at: string | null; latest_published_at: string | null; entity_match_count: number; source_status: string; fetched_at: string | null };
};
type MarketRegime = { regime: "RISK_ON" | "NEUTRAL" | "CAUTION" | "RISK_OFF"; news_direction: string; news_score: number; confidence: number; coverage_score: number; cross_source_confirmation: number; themes: Array<{ event_type: string; article_count: number }>; uncertainty: string; volatility_validation: { status: "AVAILABLE" | "UNAVAILABLE"; active_alert_count: number; has_risk_alert: boolean } };
type ResearchResponse = { company: CompanyResearch; market: MarketRegime; snapshot_id: string };

async function fetchNews(code: string, refresh: boolean): Promise<NewsResponse> {
  const params = new URLSearchParams({ limit: "20", refresh: String(refresh) });
  const response = await fetch(`/api/news/${encodeURIComponent(code)}?${params}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function fetchResearch(code: string, refresh: boolean): Promise<ResearchResponse> {
  const response = await fetch(`/api/news/${encodeURIComponent(code)}/research?refresh=${refresh}`);
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
  NO_COMPANY_NEWS: "暂无公司新闻",
  COMPANY_UNAVAILABLE: "公司源不可用",
  UNAVAILABLE: "数据源不可用",
  DISABLED: "功能已关闭",
};
const assessmentText: Record<CompanyResearch["assessment"], string> = { POSITIVE: "偏正面", NEGATIVE: "偏负面", NEUTRAL: "中性", INSUFFICIENT: "证据不足" };
const regimeText: Record<MarketRegime["regime"], string> = { RISK_ON: "风险偏好", NEUTRAL: "中性", CAUTION: "谨慎", RISK_OFF: "风险厌恶" };

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
  const research = useQuery<ResearchResponse>({ queryKey: ["news-research", submitted, refresh], queryFn: () => fetchResearch(submitted, refresh), enabled: Boolean(submitted), retry: false });
  const sources = useQuery<{ sources: NewsSource[] }>({ queryKey: ["news-sources"], queryFn: async () => { const response = await fetch("/api/news/sources"); if (!response.ok) throw new Error(await response.text()); return response.json(); }, retry: false });
  const health = useQuery<{ sources: SourceHealth[] }>({ queryKey: ["news-health"], queryFn: async () => { const response = await fetch("/api/news/health"); if (!response.ok) throw new Error(await response.text()); return response.json(); }, retry: false, refetchInterval: 30_000 });
  const candidates = useQuery<CandidateResponse>({ queryKey: ["news-factor-candidates"], queryFn: async () => { const response = await fetch("/api/news/factor/candidates"); if (!response.ok) throw new Error(await response.text()); return response.json(); }, retry: false });
  const evaluation = useQuery<FactorEvaluation>({ queryKey: ["news-factor-evaluation"], queryFn: async () => { const response = await fetch("/api/news/factor/evaluation"); if (!response.ok) throw new Error(await response.text()); return response.json(); }, retry: false });
  const [syncing, setSyncing] = useState(false);
  const buildSnapshot = async () => { setSyncing(true); try { const response = await fetch("/api/news/factor/snapshot?refresh=true", { method: "POST" }); if (!response.ok) throw new Error(await response.text()); await Promise.all([candidates.refetch(), evaluation.refetch(), health.refetch()]); } finally { setSyncing(false); } };
  const load = (force = false) => {
    if (!code) return;
    setRefresh(force);
    setSubmitted(code);
    if (code === submitted && force === refresh) void query.refetch();
  };
  const data = query.data;
  const company = research.data?.company;
  const marketRegime = research.data?.market;

  return <div className="terminal-page">
    <PageHeader
      title="新闻中心"
      description="只读新闻证据：公司新闻与市场新闻分开保存；只保留来源、标题、时间和原文链接。"
      actions={<form className="flex gap-2" onSubmit={event => { event.preventDefault(); load(false); }}>
        <MarketCodeInput market={market} value={symbol} onMarketChange={setMarket} onValueChange={setSymbol} className="w-28" />
        <button className="secondary-button" type="submit" disabled={!code || query.isFetching}>查询</button>
        <button className="primary-button flex items-center gap-1" type="button" onClick={() => load(true)} disabled={!code || query.isFetching}><RefreshCw size={14} className={query.isFetching ? "animate-spin" : ""} />刷新新闻</button>
      </form>}
    />
    {query.isError && <p className="error-banner">{query.error instanceof Error ? query.error.message : "新闻查询失败。"}</p>}
    <section className="panel p-4">
      <div className="news-summary-grid">
        <MetricCard label="终端代码" value={data?.symbol ?? submitted} />
        <MetricCard label="新闻代码" value={data?.provider_symbol ?? "—"} />
        <MetricCard label="数据状态" value={data ? statusText[data.source_status] : query.isFetching ? "加载中…" : "—"} tone={data?.source_status === "LIVE" || data?.source_status === "CACHED" ? "positive" : data?.source_status === "UNAVAILABLE" ? "negative" : "warning"} />
        <MetricCard label="更新时间" value={formatTime(data?.fetched_at ?? null)} />
      </div>
      {data?.warning && <p className="news-warning">{data.warning}</p>}
      {data?.source_warnings?.map(warning => <p key={warning} className="news-warning">{warning}</p>)}
      {data?.dropped_unapproved_sources?.length ? <p className="news-warning">未纳入情绪/建议的非白名单来源：{data.dropped_unapproved_sources.join("、")}</p> : null}
    </section>
    {research.isError && <p className="error-banner">研究卡片加载失败：{research.error instanceof Error ? research.error.message : "请稍后重试。"}</p>}
    <section className="panel mt-4 p-4">
      <div className="panel-title">公司研究卡片 <span className="float-right text-xs font-normal text-zinc-500">标题级可追溯证据，不构成交易建议</span></div>
      {!company ? <p className="muted mt-3">正在整理公司新闻研究证据…</p> : <>
        <div className="mt-3 grid grid-cols-4 gap-3 text-sm"><div><span>覆盖状态</span><b className={company.coverage_status === "AVAILABLE" ? "text-emerald-300" : "text-amber-300"}>{company.coverage_status === "AVAILABLE" ? "已覆盖" : company.coverage_status === "COVERAGE_GAP" ? "公司源覆盖不足" : "公司源不可用"}</b></div><div><span>新闻判断</span><b>{assessmentText[company.assessment]}</b></div><div><span>数据覆盖度</span><b>{(company.coverage_score * 100).toFixed(0)}%</b></div><div><span>历史预测可信度</span><b className="text-amber-300">尚未验证</b></div></div>
        {company.coverage_reason && <p className="news-warning">{company.coverage_reason}</p>}
        {company.supported_interpretation && <p className="mt-3 text-sm text-zinc-300">{company.supported_interpretation}</p>}
        {!!company.event_timeline.length && <div className="mt-3 space-y-2">{company.event_timeline.slice(0, 5).map(item => <div className="border-l-2 border-cyan-700 pl-3 text-sm" key={item.id}><span className="text-cyan-200">{item.event_type} · {item.direction} · {item.method}</span><span className="ml-2 text-zinc-500">{formatTime(item.published_at)}</span><div>{item.url ? <a className="text-zinc-200 hover:text-cyan-300" href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : item.title}</div></div>)}</div>}
        <p className="mt-3 text-xs text-zinc-500">待核实：{company.unknowns.join("；")}</p>
      </>}
    </section>
    <section className="panel mt-4 p-4">
      <div className="panel-title">美股市场风向 <span className="float-right text-xs font-normal text-zinc-500">新闻风险背景，不预测涨跌</span></div>
      {!marketRegime ? <p className="muted mt-3">正在汇总宏观新闻与波动率验证…</p> : <><div className="mt-3 grid grid-cols-4 gap-3 text-sm"><div><span>当前状态</span><b className={marketRegime.regime === "RISK_OFF" ? "text-rose-300" : marketRegime.regime === "RISK_ON" ? "text-emerald-300" : marketRegime.regime === "CAUTION" ? "text-amber-300" : ""}>{regimeText[marketRegime.regime]}</b></div><div><span>新闻方向</span><b>{marketRegime.news_direction}</b></div><div><span>跨源确认</span><b>{marketRegime.cross_source_confirmation} 个来源</b></div><div><span>证据覆盖度</span><b>{(marketRegime.coverage_score * 100).toFixed(0)}%</b></div></div><p className="mt-3 text-sm text-zinc-300">主题：{marketRegime.themes.length ? marketRegime.themes.map(item => `${item.event_type} ${item.article_count}`).join(" · ") : "暂无可分类宏观主题"}</p><p className="mt-2 text-xs text-zinc-500">波动率验证：{marketRegime.volatility_validation.status === "AVAILABLE" ? `${marketRegime.volatility_validation.active_alert_count} 个活跃预警` : "尚未完成"}；{marketRegime.uncertainty}</p></>}
    </section>
    <section className="panel mt-4 p-4"><div className="panel-title">来源健康状态</div><div className="mt-3 grid grid-cols-2 gap-2 text-xs">{(data?.source_health ?? health.data?.sources ?? []).map(source => <div className="border border-zinc-800 p-2" key={source.source_id}><b>{source.display_name}</b><span className={source.availability === "AVAILABLE" ? "ml-2 text-emerald-300" : source.availability === "UNAVAILABLE" ? "ml-2 text-amber-300" : "ml-2 text-zinc-500"}>{source.availability === "AVAILABLE" ? "可用" : source.availability === "UNAVAILABLE" ? "不可用" : "未检查"}</span><p className="mt-1 text-zinc-500">{source.scope === "COMPANY" ? "公司新闻" : "宏观新闻"} · {source.collector}</p>{source.availability_reason && <p className="mt-1 text-amber-300">原因：{source.availability_reason}</p>}<p className="mt-1 text-zinc-500">最近成功：{formatTime(source.last_success_at)}</p></div>)}</div></section>
    <section className="panel mt-4 p-4"><div className="panel-title">新闻来源白名单</div><div className="source-grid">{sources.data?.sources.map(source => <div key={source.source_id}><b>{source.display_name}</b><span>{source.enabled ? `${source.collector === "RSS" ? "已配置 RSS" : "已接入"} · ${source.scope === "MARKET" ? "市场新闻" : "公司新闻"}` : source.authorization === "LICENSE_REQUIRED" ? "需授权" : "待配置 RSS/API"}</span></div>)}</div></section>
    <section className="panel mt-4 overflow-hidden">
      <div className="news-list-title"><span>公司新闻</span><span>{data?.company_items.length ?? 0} 条</span></div>
      {query.isLoading ? <p className="muted p-4">正在获取公司新闻…</p> : !data?.company_items.length ? <p className="muted p-4">未找到 {data?.provider_symbol ?? submitted} 的可验证公司新闻。宏观 RSS 不会作为该标的新闻展示。</p> : <div className="news-list">
        {data.company_items.map(item => <article className="news-item" key={item.id}>
          <div className="news-item-meta"><span>{item.publisher ?? "未知发布者"} · {item.source} · 公司匹配</span><span>{formatTime(item.published_at)}</span></div>
          <div className="news-item-title">{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}<ExternalLink size={13} /></a> : item.title}</div>
          {item.summary && <p>{item.summary}</p>}
        </article>)}
      </div>}
    </section>
    <section className="panel mt-4 overflow-hidden">
      <div className="news-list-title"><span>宏观新闻</span><span>{data?.market_items.length ?? 0} 条</span></div>
      {query.isLoading ? <p className="muted p-4">正在获取宏观新闻…</p> : !data?.market_items.length ? <p className="muted p-4">暂无可展示的宏观新闻。</p> : <div className="news-list">{data.market_items.map(item => <article className="news-item" key={item.id}><div className="news-item-meta"><span>{item.source} · 宏观</span><span>{formatTime(item.published_at)}</span></div><div className="news-item-title">{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}<ExternalLink size={13} /></a> : item.title}</div></article>)}</div>}
    </section>
    <section className="panel mt-4 p-4"><div className="panel-title">因子样本外验证</div><p className={evaluation.data?.status === "VALIDATED" ? "mt-3 text-emerald-300" : "mt-3 text-amber-300"}>{evaluation.data?.status === "VALIDATED" ? "已通过预设统计门槛" : "尚未验证：证据不足"}</p><p className="mt-2 text-xs text-zinc-500">{evaluation.data?.reason ?? `可对齐样本 ${evaluation.data?.sample_count ?? 0} 条；仅通过后才允许 POSITIVE_WATCH / NEUTRAL / NEGATIVE_AVOID。`}</p>{evaluation.data?.horizons.map(item => <p className="mt-2 text-xs" key={item.horizon}>{item.horizon} 日：IC {item.spearman_ic?.toFixed(3) ?? "—"} · t {item.t_stat?.toFixed(2) ?? "—"} · ICIR {item.icir?.toFixed(2) ?? "—"} · 样本 {item.sample_count}</p>)}</section>
    <section className="panel mt-4 overflow-hidden"><div className="news-list-title"><span>新闻研究候选 <small className="text-zinc-500">不构成交易建议</small></span><button className="secondary-button" disabled={syncing} onClick={() => void buildSnapshot()}>{syncing ? "生成中…" : "生成因子快照"}</button></div>{candidates.data?.status === "NO_SNAPSHOT" ? <p className="muted p-4">{candidates.data.message}</p> : <div className="news-list">{candidates.data?.candidates.map(candidate => <article className="news-item" key={candidate.symbol}><div className="news-item-meta"><span>{candidate.symbol} · {candidate.research_state === "INSUFFICIENT_EVIDENCE" ? "证据不足" : candidate.research_state}</span><span>等权基准分 {candidate.news_score.toFixed(3)} · {candidate.article_count} 篇</span></div><div className="news-item-title">GPMA {candidate.technical.gpma_bullish && candidate.technical.gpma_active_buy ? "多头 B 信号" : "未确认"} · DELTA {candidate.technical.delta_low_active ? "低点窗口" : "未确认"}</div><p>最早研究交易时间：{candidate.earliest_trade_at ?? "无合格新闻"}</p>{candidate.evidence.slice(0, 2).map(item => <p key={item.id}>{item.publisher}｜{item.title}</p>)}</article>)}</div>}</section>
  </div>;
}
