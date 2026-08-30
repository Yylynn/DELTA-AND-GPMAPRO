import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { MarketCodeInput } from "@/components/MarketCodeInput";
import { PageHeader, StatusBadge } from "@/components/ui/workspace";
import { resolveMarketCode, type Market } from "@/lib/marketCode";
import { OptionsMarketSummary } from "@/components/OptionsMarketSummary";

type Action = "BUY" | "ACCUMULATE" | "HOLD" | "REDUCE" | "SELL";
type Bias = "BULLISH" | "NEUTRAL" | "BEARISH";
type BadgeTone = "neutral" | "positive" | "warning" | "negative" | "info";

type SourceHealth = {
  source_id: string;
  display_name: string;
  scope: "COMPANY" | "MARKET";
  collector: string;
  status: "OK" | "DEGRADED" | "NO_DATA" | "NOT_CONFIGURED" | "UNKNOWN";
  availability: "AVAILABLE" | "NO_DATA" | "NOT_CONFIGURED" | "UNAVAILABLE" | "NOT_CHECKED";
  availability_reason: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
};

type NewsItem = {
  id: string;
  symbol: string;
  title: string;
  url: string | null;
  source: string;
  source_id?: string;
  publisher?: string;
  published_at: string | null;
  summary: string | null;
  entity_status?: "ACCEPTED" | "REJECTED_ENTITY_MISMATCH";
  factor_eligible?: boolean;
  scope?: "COMPANY" | "MARKET";
  thumbnail?: string | null;
};

type HeadlineGroup = { id: string; label: string; source_ids: string[]; available: boolean; count: number; items: NewsItem[] };

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
  source_health?: SourceHealth[];
};

type MarketNewsResponse = {
  market_items: NewsItem[];
  source_status: "LIVE" | "CACHED" | "STALE_CACHE" | "NO_DATA" | "UNAVAILABLE" | "DISABLED";
  fetched_at: string | null;
  is_cached: boolean;
  warning: string | null;
  source_warnings: string[];
  source_health: SourceHealth[];
  source_order: string[];
  headline_groups: HeadlineGroup[];
};

type RadarTransmission = { asset: string; sector: string; direction: "BULLISH" | "BEARISH" | "UNCERTAIN"; basis: string; kind: "ETF" | "STOCK" };
type RadarReactionItem = RadarTransmission & { benchmark: string; returns: Record<string, number>; excess_returns: Record<string, number> };
type RadarEvent = {
  event_id: string; title: string; translated_title?: string | null; summary: string | null; published_at: string | null;
  themes: Array<{ id: string; label: string }>; direction_score: number; confidence: number;
  industries: Array<"科技" | "金融" | "消费" | "医疗" | "能源" | "工业" | "加密" | "宏观综合">;
  confirmation: "CONFIRMED" | "PENDING"; confirmation_reason: string;
  source_confidence: number; information_completeness: number; transmission: RadarTransmission[];
  headline: { kind: "网站头条" | "官方发布"; priority: number; reason: string };
  interpretation: { fact_summary: string; basis: string; conclusion: string; limitation: string };
  evidence: NewsItem[]; representative_source: Pick<NewsItem, "source" | "source_id" | "publisher" | "url" | "published_at">;
  reaction: { status: "AVAILABLE" | "PENDING" | "UNAVAILABLE"; items: RadarReactionItem[]; message: string };
};

type MarketRadar = {
  posture: "DEFENSIVE" | "NEUTRAL" | "CONSTRUCTIVE";
  market_score: number;
  confidence: number;
  events: RadarEvent[];
  industry_counts: Partial<Record<RadarEvent["industries"][number], number>>;
  scenarios: Array<{ kind: string; text: string }>;
  validation: { status: string; session_count: number; reason: string };
  active_alerts: Array<{ display_label?: string; message?: string; severity?: string }>;
  headline_event_map: Record<string, string>;
};

type AdviceEvidence = {
  id: string;
  title: string;
  url: string | null;
  source?: string;
  source_id?: string;
  publisher?: string;
  published_at: string | null;
  earliest_trade_at: string | null;
  summary?: string | null;
  eligible: boolean;
  exclusion_reason: string | null;
  direction: string;
  event_type: string;
  method: string;
  high_impact: boolean;
  contribution: number;
};

type AdviceEvent = {
  cluster_id: string;
  title: string;
  event_type: string;
  direction: number;
  high_impact: boolean;
  source_count: number;
  sources: string[];
  published_at: string | null;
  earliest_trade_at: string | null;
  contribution: number;
  evidence_ids: string[];
};

type MarketRegime = {
  regime: "RISK_ON" | "NEUTRAL" | "CAUTION" | "RISK_OFF";
  news_direction: string;
  news_score: number;
  confidence: number;
  coverage_score: number;
  cross_source_confirmation: number;
  themes: Array<{ event_type: string; article_count: number }>;
  uncertainty: string;
  volatility_validation: { status: string; active_alert_count: number; has_risk_alert: boolean };
};

type NewsAdvice = {
  symbol: string;
  as_of: string;
  factor_version: string;
  status: "AVAILABLE" | "INSUFFICIENT_EVIDENCE" | "STALE" | "UNAVAILABLE";
  action: Action;
  action_label: string;
  position_guidance: string;
  bias: Bias;
  score: number;
  confidence: number;
  validation_status: string;
  validation: FactorEvaluation;
  concise_reason: string;
  components: Record<string, number>;
  market_regime: MarketRegime;
  contribution: { enabled: boolean; positive_cap: number; negative_cap: number; points: number; effect: string };
  research_guidance: { status: string; bias: Bias; confidence: number; summary: string; catalysts: string[]; risks: string[]; limitations: string[] };
  key_reasons: string[];
  risk_flags: string[];
  events: AdviceEvent[];
  evidence: AdviceEvidence[];
  data_quality: {
    article_count: number;
    valid_article_count: number;
    unique_event_count: number;
    duplicate_count: number;
    source_count: number;
    published_at_completeness: number;
    model_eligibility_rate: number;
    model_status: string;
    coverage_gaps: string[];
    source_status: string;
    fetched_at: string | null;
    is_cached: boolean;
    stale: boolean;
    warning?: string | null;
  };
  earliest_trade_at: string | null;
  expires_at: string | null;
};

type ScorecardEvent = {
  event_id: string;
  title: string;
  event_type: string;
  direction: "BULLISH" | "BEARISH" | "UNKNOWN";
  importance: "HIGH" | "STANDARD";
  impact_horizon: string;
  published_at: string | null;
  earliest_trade_at: string | null;
  source_count: number;
  confidence: number;
  affected_ticker: string;
  sector_benchmark: string;
  evidence: Array<{ id: string; title: string; url: string | null; source: string; published_at: string | null }>;
  reaction: { status: "AVAILABLE" | "PENDING" | "UNAVAILABLE"; stock_returns: Record<string, number>; spy_excess_returns: Record<string, number>; sector_excess_returns: Record<string, number>; volume_surprise: Record<string, number>; volatility_change: Record<string, number>; message: string };
};

type NewsScorecard = {
  schema_version: number;
  research_only: true;
  generated_at: string;
  symbol: string;
  sector_benchmark: string;
  data_status: string;
  impact_score: number;
  historical_reliability: { status: string; validated: boolean; sample_count: number; session_count: number; message: string };
  market_regime: MarketRegime;
  events: ScorecardEvent[];
  data_quality: { scorecard_message: string };
  limitations: string[];
};

type Candidate = {
  symbol: string;
  tier: "FOCUS" | "WATCH" | "FILTERED";
  research_state: string;
  news_score: number;
  article_count: number;
  negative_catalyst: boolean;
  earliest_trade_at: string | null;
  validation_status: string;
};

type CandidateResponse = {
  status: string;
  snapshot_at?: string;
  validation_status?: string;
  snapshot_quality?: string;
  candidates: Candidate[];
  message: string;
};

type FactorEvaluation = {
  status: "VALIDATED" | "INSUFFICIENT_EVIDENCE";
  factor_version?: string;
  sample_count: number;
  session_count?: number;
  reason?: string;
  horizons: Array<{
    horizon: number;
    status: string;
    sample_count: number;
    spearman_ic?: number;
    t_stat?: number;
    icir?: number;
    walk_forward?: { oos_sharpe_after_cost: number; test_count: number };
  }>;
};

type NewsSource = {
  source_id: string;
  display_name: string;
  authorization: string;
  enabled: boolean;
  kind: string;
  collector: string;
  scope: string;
};

type Props = {
  initialCode?: string;
  initialDetailsOpen?: boolean;
  contextKey?: number;
  onOpenOptions?: () => void;
  onOpenOverview?: (symbol: string) => void;
};

type NewsTab = "company" | "market";

const componentMeta: Record<string, { label: string; weight: string }> = {
  short_term_sentiment: { label: "24 小时情绪", weight: "40%" },
  weekly_sentiment: { label: "7 日情绪", weight: "25%" },
  major_event_impact: { label: "重大事件", weight: "15%" },
  directional_breadth: { label: "方向广度", weight: "10%" },
  attention_surprise: { label: "异常关注度", weight: "10%" },
  negative_tail_risk: { label: "重大负面尾部", weight: "扣减 25%" },
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败 (${response.status})`);
  }
  return response.json();
}

function actionClass(action: Action) {
  return `news-action-${action.toLowerCase()}`;
}

function actionEnglish(action: Action) {
  return { BUY: "BUY", ACCUMULATE: "ACCUMULATE", HOLD: "HOLD", REDUCE: "REDUCE", SELL: "SELL" }[action];
}

function biasText(bias: Bias) {
  return { BULLISH: "偏多", NEUTRAL: "中性", BEARISH: "偏空" }[bias];
}

function regimeText(regime?: MarketRegime["regime"]) {
  return { RISK_ON: "风险偏好", NEUTRAL: "中性", CAUTION: "谨慎", RISK_OFF: "风险厌恶" }[regime ?? "NEUTRAL"];
}

function adviceStatusText(status: NewsAdvice["status"]) {
  return { AVAILABLE: "可用", INSUFFICIENT_EVIDENCE: "证据不足", STALE: "缓存过期", UNAVAILABLE: "不可用" }[status];
}

function toneForDirection(direction: string | number): BadgeTone {
  const numeric = typeof direction === "number" ? direction : direction === "POSITIVE" ? 1 : direction === "NEGATIVE" ? -1 : 0;
  return numeric > 0.14 ? "positive" : numeric < -0.14 ? "negative" : "neutral";
}

function formatTime(value?: string | null) {
  if (!value) return "暂无";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function signed(value: number, digits = 2) {
  const normalized = Math.abs(value) < 0.0005 ? 0 : value;
  return `${normalized > 0 ? "+" : ""}${normalized.toFixed(digits)}`;
}

function initialMarket(code: string): Market {
  if (code.toUpperCase().startsWith("HK.")) return "HK";
  if (code.toUpperCase().startsWith("SH.") || code.toUpperCase().startsWith("SZ.")) return "A";
  return "US";
}

function initialTicker(code: string) {
  return code.includes(".") ? code.split(".").slice(1).join(".") : code;
}

function NewsList({ title, caption, items, pageSize = 20 }: { title: string; caption: string; items: NewsItem[]; pageSize?: number }) {
  const [visibleCount, setVisibleCount] = useState(pageSize);
  useEffect(() => setVisibleCount(pageSize), [items, pageSize]);
  const visibleItems = items.slice(0, visibleCount);
  return (
    <section className="panel news-stream-panel">
      <div className="news-section-heading">
        <div>
          <span className="news-eyebrow">EVIDENCE STREAM</span>
          <h2>{title}</h2>
        </div>
        <span>{caption}</span>
      </div>
      {items.length ? (
        <div className="news-compact-list">
          {visibleItems.map((item) => (
            <article className="news-compact-item" key={`${item.id}-${item.published_at}`}>
              <div className="news-compact-meta">
                <span>{item.publisher || item.source}</span>
                <time>{formatTime(item.published_at)}</time>
              </div>
              <h3>
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer">
                    {item.title}<ExternalLink size={13} aria-hidden="true" />
                  </a>
                ) : item.title}
              </h3>
              {item.summary && <p>{item.summary}</p>}
            </article>
          ))}
          {visibleItems.length < items.length && <button className="news-load-more" type="button" onClick={() => setVisibleCount((count) => count + pageSize)}>加载更多新闻（已显示 {visibleItems.length} / {items.length}）</button>}
        </div>
      ) : (
        <div className="news-empty-state">
          <strong>当前窗口没有可展示的新闻</strong>
          <span>新闻缺失不会被解释为中性信号，总览贡献保持为 0。</span>
        </div>
      )}
    </section>
  );
}

function HeadlineBoard({ groups, activeSource, onSourceChange, onSelect, status }: { groups: HeadlineGroup[]; activeSource: string; onSourceChange: (source: string) => void; onSelect: (item: NewsItem) => void; status: MarketNewsResponse["source_status"] }) {
  const [visibleCount, setVisibleCount] = useState(5);
  const active = groups.find((group) => group.id === activeSource) ?? groups[0];
  const items = active?.items ?? [];
  const visible = items.slice(0, visibleCount);
  useEffect(() => setVisibleCount(5), [activeSource]);
  const card = (item: NewsItem, primary: boolean) => <article className={`market-headline-card ${primary ? "is-primary" : "is-secondary"} ${item.thumbnail ? "has-image" : "is-text-only"}`} key={item.id}>
    {item.thumbnail && <img src={item.thumbnail} alt="" loading={primary ? "eager" : "lazy"} />}
    <div className="market-headline-scrim" aria-hidden="true" />
    <div className="market-headline-content"><div className="market-headline-meta"><span>{item.source || item.publisher}</span><time>{formatTime(item.published_at)}</time></div><h3>{item.title}</h3><div className="market-headline-actions"><button type="button" onClick={() => onSelect(item)}>查看分析</button>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">原文 <ExternalLink size={12} aria-hidden="true" /></a> : <span>无原文链接</span>}</div></div>
  </article>;
  return <section className="market-headline-workspace" aria-label="来源头条"><div className="news-subheading market-headline-heading"><div><h2>今日宏观头条</h2><p>按发布来源查看最新标题，新闻正文不会被抓取。</p></div><StatusBadge tone={status === "LIVE" || status === "CACHED" ? "positive" : status === "STALE_CACHE" ? "warning" : "negative"}>{status === "STALE_CACHE" ? "缓存过期" : status}</StatusBadge></div>
    <div className="market-headline-tabs" role="tablist" aria-label="宏观新闻来源">{groups.map((group) => <button type="button" role="tab" aria-selected={group.id === activeSource} className={group.id === activeSource ? "active" : ""} disabled={!group.available} onClick={() => onSourceChange(group.id)} key={group.id}>{group.label}<span>{group.count}</span></button>)}</div>
    {visible.length ? <><div className="market-headline-grid">{card(visible[0], true)}<div className="market-headline-secondary-grid">{visible.slice(1, 5).map((item) => card(item, false))}</div></div>{visibleCount < items.length && <button className="news-load-more" type="button" onClick={() => setVisibleCount((count) => count + 5)}>查看更多头条（已显示 {Math.min(visibleCount, items.length)} / {items.length}）</button>}{visible.length > 5 && <div className="market-headline-more">{visible.slice(5).map((item) => card(item, false))}</div>}</> : <div className="news-empty-state compact"><strong>该来源暂无可用头条</strong><span>来源恢复后会在下一次 15 分钟刷新中自动出现。</span></div>}
  </section>;
}

function transmissionDirection(direction: RadarTransmission["direction"]) {
  return direction === "BULLISH" ? "预期利多" : direction === "BEARISH" ? "预期利空" : "方向不确定";
}

function RadarEventCard({ event, onOpenOverview, selected = false }: { event: RadarEvent; onOpenOverview: (symbol: string) => void; selected?: boolean }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (selected && detailsRef.current) detailsRef.current.open = true; }, [selected]);
  const representative = event.representative_source;
  const targets = [...event.transmission].sort((left, right) => (left.kind === right.kind ? left.asset.localeCompare(right.asset) : left.kind === "STOCK" ? -1 : 1));
  return (
    <article className={`news-radar-event panel ${selected ? "is-selected" : ""}`} id={`market-event-${event.event_id}`}>
      <div className="news-radar-event-header">
        <div className="news-event-meta">
          {event.themes.map((theme) => <StatusBadge tone="info" key={theme.id}>{theme.label}</StatusBadge>)}
          <StatusBadge tone={event.headline.kind === "官方发布" ? "positive" : "neutral"}>{event.headline.kind}</StatusBadge>
          <StatusBadge tone={event.confirmation === "CONFIRMED" ? "positive" : "warning"}>{event.confirmation === "CONFIRMED" ? "已确认" : "待确认"}</StatusBadge>
        </div>
        <h3>{event.translated_title || event.interpretation.fact_summary}</h3>
        {event.translated_title && event.summary && <p>{event.summary}</p>}
        <p className="news-radar-original-title"><span>英文原题</span>{event.title}</p>
        <div className="news-radar-source">
          <span>{representative.publisher || representative.source || "未知来源"} · {formatTime(representative.published_at || event.published_at)}</span>
          {representative.url ? <a href={representative.url} target="_blank" rel="noreferrer">原文 <ExternalLink size={12} /></a> : <span>来源未提供原文链接</span>}
        </div>
      </div>
      <section className="news-radar-transmission" aria-label="可能传导至的标的">
        <div className="news-radar-transmission-heading"><strong>可能传导至</strong><span>核心个股优先，ETF 作为行业基准</span></div>
        {targets.length ? <div className="news-radar-targets">{targets.map((row) => <button type="button" className={`news-radar-target news-radar-target-${row.direction.toLowerCase()}`} key={row.asset} onClick={() => onOpenOverview(`US.${row.asset}`)} aria-label={`在总览中查看 ${row.asset} 的 DELTA 和技术指标`}><div><b>{row.asset}</b><StatusBadge tone={row.direction === "BULLISH" ? "positive" : row.direction === "BEARISH" ? "negative" : "warning"}>{transmissionDirection(row.direction)}</StatusBadge></div><span>{row.kind === "ETF" ? "行业基准" : "核心个股"} · {row.sector}</span><p>{row.basis}</p><small>点击查看 DELTA 与技术指标</small></button>)}</div> : <div className="news-radar-target-empty"><strong>尚无可审计传导标的</strong><span>传导链路不足，系统不会强行映射股票。</span></div>}
      </section>
      <details className="news-radar-details" ref={detailsRef}>
        <summary>查看事件解读、来源与后续反应</summary>
        <p className="news-radar-confirmation">{event.confirmation_reason}</p>
        <section className="news-radar-interpretation"><strong>事件解读</strong><div><b>新闻要点</b><p>{event.interpretation.fact_summary}</p></div><div><b>影响路径</b><p>{event.interpretation.conclusion}</p></div><small>{event.interpretation.basis} {event.interpretation.limitation}</small></section>
        <dl className="news-radar-confidence"><div><dt>来源确认度</dt><dd>{Math.round(event.source_confidence * 100)}%</dd></div><div><dt>信息完整度</dt><dd>{Math.round(event.information_completeness * 100)}%</dd></div></dl>
        <section className="news-radar-reaction-block"><strong>事件后反应</strong>{event.reaction.status === "AVAILABLE" ? event.reaction.items.map((item) => <p key={item.asset}><b>{item.asset}</b> · 相对 {item.benchmark}：1日 {signed((item.excess_returns["1d"] ?? 0) * 100)}% · 3日 {signed((item.excess_returns["3d"] ?? 0) * 100)}% · 5日 {signed((item.excess_returns["5d"] ?? 0) * 100)}%</p>) : <p>{event.reaction.status === "PENDING" ? "等待可观测交易日：" : "行情不可用："}{event.reaction.message}</p>}{event.reaction.status === "AVAILABLE" && <small>{event.reaction.message}</small>}</section>
        <details className="news-radar-evidence"><summary>全部来源（{event.evidence.length}）</summary>{event.evidence.map((item) => <div key={item.id}><span>{item.publisher || item.source} · {formatTime(item.published_at)}</span>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : <b>{item.title}（无原文链接）</b>}{item.summary && <p>{item.summary}</p>}</div>)}</details>
        <small className="news-radar-disclaimer">传导为待验证规则推断，不代表因果或交易指令。</small>
      </details>
    </article>
  );
}

export function NewsCenter({ initialCode = "US.AAPL", initialDetailsOpen = false, contextKey = 0, onOpenOptions = () => undefined, onOpenOverview = () => undefined }: Props) {
  const [market, setMarket] = useState<Market>(() => initialMarket(initialCode));
  const [ticker, setTicker] = useState(() => initialTicker(initialCode));
  const [code, setCode] = useState(initialCode.toUpperCase());
  const [refresh, setRefresh] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(initialDetailsOpen);
  const [inputError, setInputError] = useState<string | null>(null);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<NewsTab>("market");
  const [activeHeadlineSource, setActiveHeadlineSource] = useState("all");
  const [selectedHeadlineId, setSelectedHeadlineId] = useState<string | null>(null);
  const [eventVisibleCount, setEventVisibleCount] = useState(8);

  useEffect(() => {
    const nextCode = initialCode.toUpperCase();
    setMarket(initialMarket(nextCode));
    setTicker(initialTicker(nextCode));
    setCode(nextCode);
    setDetailsOpen(initialDetailsOpen);
  }, [contextKey, initialCode, initialDetailsOpen]);

  const adviceQuery = useQuery({
    queryKey: ["news-advice", code, refresh],
    queryFn: () => fetchJson<NewsAdvice>(`/api/news/${encodeURIComponent(code)}/advice?refresh=${refresh}`),
    retry: 1, enabled: activeTab === "company",
  });
  const newsQuery = useQuery({
    queryKey: ["news", code, refresh],
    queryFn: () => fetchJson<NewsResponse>(`/api/news/${encodeURIComponent(code)}?limit=30&refresh=${refresh}`),
    retry: 1, enabled: activeTab === "company",
  });
  const scorecardQuery = useQuery({
    queryKey: ["news-scorecard", code, refresh],
    queryFn: () => fetchJson<NewsScorecard>(`/api/news/${encodeURIComponent(code)}/scorecard?refresh=${refresh}`),
    retry: 1, enabled: activeTab === "company",
  });
  const marketQuery = useQuery({
    queryKey: ["market-news", refresh],
    queryFn: () => fetchJson<MarketNewsResponse>(`/api/news/market?limit=100&refresh=${refresh}`),
    retry: 1, enabled: activeTab === "market", refetchInterval: 900_000,
  });
  const radarQuery = useQuery({
    queryKey: ["market-event-radar", refresh],
    queryFn: () => fetchJson<MarketRadar>(`/api/news/market/radar?refresh=${refresh}`),
    retry: 1, enabled: activeTab === "market",
  });
  const sourceQuery = useQuery({ queryKey: ["news-sources"], queryFn: () => fetchJson<{ sources: NewsSource[] }>("/api/news/sources") });
  const healthQuery = useQuery({ queryKey: ["news-health"], queryFn: () => fetchJson<{ sources: SourceHealth[] }>("/api/news/health") });
  const candidateQuery = useQuery({ queryKey: ["news-candidates"], queryFn: () => fetchJson<CandidateResponse>("/api/news/factor/candidates?limit=8") });
  const evaluationQuery = useQuery({ queryKey: ["news-evaluation"], queryFn: () => fetchJson<FactorEvaluation>("/api/news/factor/evaluation") });

  const runQuery = (force = false) => {
    try {
      const nextCode = resolveMarketCode(ticker, market);
      setInputError(null);
      if (nextCode === code && force === refresh) {
        void Promise.all([adviceQuery.refetch(), newsQuery.refetch(), scorecardQuery.refetch()]);
      } else {
        setCode(nextCode);
        setRefresh(force);
      }
    } catch (error) {
      setInputError(error instanceof Error ? error.message : String(error));
    }
  };

  const refreshMarket = () => {
    if (refresh) void Promise.all([marketQuery.refetch(), radarQuery.refetch()]);
    else setRefresh(true);
  };

  const buildSnapshot = async () => {
    setSnapshotBusy(true);
    setSnapshotError(null);
    try {
      await fetchJson("/api/news/factor/snapshot?refresh=true", { method: "POST" });
      await Promise.all([candidateQuery.refetch(), evaluationQuery.refetch()]);
    } catch (error) {
      setSnapshotError(error instanceof Error ? error.message : String(error));
    } finally {
      setSnapshotBusy(false);
    }
  };

  const fallbackAdvice = useMemo<NewsAdvice>(() => ({
    symbol: code,
    as_of: new Date().toISOString(),
    factor_version: "NEWS_FACTOR_V3",
    status: "UNAVAILABLE",
    action: "HOLD",
    action_label: "观望",
    position_guidance: "维持现有仓位，不依据新闻执行交易。",
    bias: "NEUTRAL",
    score: 0,
    confidence: 0,
    validation_status: "INSUFFICIENT_EVIDENCE",
    validation: { status: "INSUFFICIENT_EVIDENCE", sample_count: 0, horizons: [] },
    concise_reason: "新闻建议暂时不可用，保持观望且不参与总览决策。",
    components: {},
    market_regime: { regime: "NEUTRAL", news_direction: "NEUTRAL", news_score: 0, confidence: 0, coverage_score: 0, cross_source_confirmation: 0, themes: [], uncertainty: "新闻风险背景暂时不可用。", volatility_validation: { status: "UNAVAILABLE", active_alert_count: 0, has_risk_alert: false } },
    contribution: { enabled: false, positive_cap: 5, negative_cap: 15, points: 0, effect: "NONE" },
    research_guidance: { status: "INSUFFICIENT", bias: "NEUTRAL", confidence: 0, summary: "暂无研究级解读。", catalysts: [], risks: [], limitations: [] },
    key_reasons: [],
    risk_flags: ["新闻接口不可用，本次总览贡献为 0。"],
    events: [],
    evidence: [],
    data_quality: { article_count: 0, valid_article_count: 0, unique_event_count: 0, duplicate_count: 0, source_count: 0, published_at_completeness: 0, model_eligibility_rate: 0, model_status: "UNAVAILABLE", coverage_gaps: [], source_status: "UNAVAILABLE", fetched_at: null, is_cached: false, stale: true },
    earliest_trade_at: null,
    expires_at: null,
  }), [code]);

  const advice = adviceQuery.data ?? fallbackAdvice;
  const news = newsQuery.data;
  const scorecard = scorecardQuery.data;
  const evaluation = evaluationQuery.data ?? advice.validation;
  const heroError = inputError || (adviceQuery.error instanceof Error ? adviceQuery.error.message : null);
  const validationTone: BadgeTone = advice.validation_status === "VALIDATED" ? "positive" : "warning";
  const sourceTone: BadgeTone = advice.status === "AVAILABLE" ? "positive" : advice.status === "STALE" ? "warning" : "negative";
  const radarEvents = radarQuery.data?.events ?? [];
  const selectedEventId = selectedHeadlineId ? radarQuery.data?.headline_event_map?.[selectedHeadlineId] : undefined;
  const selectHeadline = (item: NewsItem) => {
    setSelectedHeadlineId(item.id);
    const eventId = radarQuery.data?.headline_event_map?.[item.id];
    const eventIndex = eventId ? radarEvents.findIndex((event) => event.event_id === eventId) : -1;
    if (eventIndex >= eventVisibleCount) setEventVisibleCount(eventIndex + 1);
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    window.setTimeout(() => document.getElementById(eventId ? `market-event-${eventId}` : "market-raw-evidence")?.scrollIntoView({ behavior, block: "start" }), 50);
  };

  return (
    <div className="terminal-page news-decision-page">
      <PageHeader
        title="新闻中心"
        description={activeTab === "company" ? "先看新闻建议，再按需核对因子、事件与原始证据。新闻仅用于研究辅助，不构成交易指令。" : "跟踪市场风险背景与宏观主题；宏观新闻不会直接生成个股交易结论。"}
        actions={activeTab === "company" ? (
          <form className="news-query-form" onSubmit={(event) => { event.preventDefault(); runQuery(false); }}>
            <MarketCodeInput market={market} value={ticker} onMarketChange={setMarket} onValueChange={setTicker} className="news-code-input" />
            <button className="secondary-button" type="submit">查询</button>
            <button className="primary-button news-refresh-button" type="button" onClick={() => runQuery(true)} disabled={adviceQuery.isFetching || newsQuery.isFetching}>
              <RefreshCw size={15} aria-hidden="true" />
              刷新新闻
            </button>
          </form>
        ) : (
          <button className="primary-button news-refresh-button" type="button" onClick={refreshMarket} disabled={marketQuery.isFetching}>
            <RefreshCw size={15} aria-hidden="true" />刷新宏观新闻
          </button>
        )}
      />

      <div className="news-tab-list" role="tablist" aria-label="新闻类型">
        <button type="button" role="tab" aria-selected={activeTab === "market"} className={activeTab === "market" ? "active" : ""} onClick={() => setActiveTab("market")}>宏观新闻</button>
        <button type="button" role="tab" aria-selected={activeTab === "company"} className={activeTab === "company" ? "active" : ""} onClick={() => setActiveTab("company")}>公司新闻</button>
      </div>

      {activeTab === "company" && <>

      {adviceQuery.isLoading ? (
        <section className="news-advice-skeleton" aria-label="正在加载新闻建议">
          <div /><div /><div />
        </section>
      ) : (
        <section className={`news-advice-hero ${actionClass(advice.action)}`}>
          <div className="news-advice-primary">
            <div className="news-advice-kicker">
              <span>NEWS ADVICE</span>
              <StatusBadge tone={validationTone}>{advice.validation_status === "VALIDATED" ? "已验证" : "证据不足"}</StatusBadge>
            </div>
            <div className="news-action-line">
              <h2>{advice.action_label}</h2>
              <span>{actionEnglish(advice.action)}</span>
            </div>
            <p className="news-position-guidance">{advice.position_guidance}</p>
            <p className="news-concise-reason">{advice.concise_reason}</p>
            {heroError && <div className="news-inline-error" role="alert">{heroError}</div>}
          </div>

          <div className="news-advice-metrics">
            <article>
              <span>新闻偏向</span>
              <strong>{biasText(advice.bias)}</strong>
              <small>因子分数 {signed(advice.score)}</small>
            </article>
            <article>
              <span>24 小时方向</span>
              <strong>{signed(advice.components.short_term_sentiment ?? 0)}</strong>
              <small>短期权重 40%</small>
            </article>
            <article>
              <span>7 日方向</span>
              <strong>{signed(advice.components.weekly_sentiment ?? 0)}</strong>
              <small>周度权重 25%</small>
            </article>
            <article>
              <span>可信度</span>
              <strong>{Math.round(advice.confidence * 100)}%</strong>
              <small>{advice.data_quality.unique_event_count} 个独立事件簇</small>
            </article>
          </div>

          <aside className="news-advice-side">
            <div>
              <span>总览新闻调整</span>
              <strong>{signed(advice.contribution.points, 1)} 分</strong>
              <small>正面上限 +5，负面下限 -15</small>
            </div>
            <dl>
              <div><dt>市场环境</dt><dd>{regimeText(advice.market_regime.regime)}</dd></div>
              <div><dt>数据状态</dt><dd><StatusBadge tone={sourceTone}>{adviceStatusText(advice.status)}</StatusBadge></dd></div>
              <div><dt>数据时间</dt><dd>{formatTime(advice.data_quality.fetched_at)}</dd></div>
            </dl>
            <button className="news-detail-toggle" type="button" onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen}>
              {detailsOpen ? "收起详细分析" : "查看详细分析"}
              <ChevronDown size={16} aria-hidden="true" />
            </button>
          </aside>
        </section>
      )}

      <section className="news-research-guidance panel" aria-label="研究级公司解读">
        <div><span className="news-eyebrow">RESEARCH GUIDANCE</span><h3>研究级解读 · {biasText(advice.research_guidance.bias)}</h3><p>{advice.research_guidance.summary}</p></div>
        <dl><div><dt>研究置信度</dt><dd>{Math.round(advice.research_guidance.confidence * 100)}%</dd></div><div><dt>催化剂</dt><dd>{advice.research_guidance.catalysts.length || "暂无"}</dd></div><div><dt>风险项</dt><dd>{advice.research_guidance.risks.length || "暂无"}</dd></div></dl>
        {advice.research_guidance.limitations.map((item) => <small key={item}>{item}</small>)}
      </section>

      <section className="news-scorecard panel" aria-label="新闻影响评分卡">
        <div className="news-section-heading">
          <div><span className="news-eyebrow">IMPACT SCORECARD · RESEARCH ONLY</span><h2>新闻影响评分卡</h2></div>
          <StatusBadge tone={scorecard?.historical_reliability.validated ? "positive" : "warning"}>{scorecard?.historical_reliability.validated ? "样本外已验证" : "仅研究观察"}</StatusBadge>
        </div>
        {scorecard ? <>
          <p className="news-scorecard-summary">{scorecard.historical_reliability.message} {scorecard.data_quality.scorecard_message}</p>
          <div className="news-scorecard-metrics">
            <article><span>个股影响分</span><strong>{signed(scorecard.impact_score)}</strong><small>{scorecard.symbol}</small></article>
            <article><span>行业对照</span><strong>{scorecard.sector_benchmark}</strong><small>相对行业 ETF 的超额收益</small></article>
            <article><span>有效交易日</span><strong>{scorecard.historical_reliability.session_count}</strong><small>当前样本 {scorecard.historical_reliability.sample_count} 条</small></article>
          </div>
          {scorecard.events.length ? <div className="news-event-grid news-scorecard-events">
            {scorecard.events.map((event) => <article className={`news-event-card border-${toneForDirection(event.direction === "BULLISH" ? 1 : event.direction === "BEARISH" ? -1 : 0)}`} key={event.event_id}>
              <div className="news-event-meta"><StatusBadge tone={toneForDirection(event.direction === "BULLISH" ? 1 : event.direction === "BEARISH" ? -1 : 0)}>{event.event_type}</StatusBadge><StatusBadge tone={event.importance === "HIGH" ? "warning" : "neutral"}>{event.importance === "HIGH" ? "高影响" : "一般影响"}</StatusBadge></div>
              <h4>{event.title}</h4>
              <p>{event.affected_ticker} → {event.sector_benchmark} · {event.source_count} 个独立来源 · 置信度 {Math.round(event.confidence * 100)}%</p>
              <dl><div><dt>观察窗口</dt><dd>{event.impact_horizon}</dd></div><div><dt>最早可交易</dt><dd>{formatTime(event.earliest_trade_at)}</dd></div></dl>
              {event.reaction.status === "AVAILABLE" ? <p className="news-scorecard-reaction">事件后：个股 1日 {signed((event.reaction.stock_returns["1d"] ?? 0) * 100)}% · 相对 SPY {signed((event.reaction.spy_excess_returns["1d"] ?? 0) * 100)}% · 相对 {event.sector_benchmark} {signed((event.reaction.sector_excess_returns["1d"] ?? 0) * 100)}%</p> : <p className="news-scorecard-reaction">{event.reaction.message}</p>}
              {event.evidence[0]?.url && <a className="news-scorecard-source" href={event.evidence[0].url} target="_blank" rel="noreferrer">查看原始证据 <ExternalLink size={13} /></a>}
            </article>)}
          </div> : <div className="news-empty-state compact"><strong>尚未形成可评分事件</strong><span>没有合格事件或数据不足会被明确标记，不会被解释为中性。</span></div>}
          <small className="news-scorecard-limitations">{scorecard.limitations.join(" · ")}</small>
        </> : <div className="news-empty-state compact"><strong>评分卡加载中或暂不可用</strong><span>不会影响现有新闻证据和技术分析。</span></div>}
      </section>

      {detailsOpen && (
        <section className="news-analysis-detail" aria-label="新闻详细分析">
          <div className="news-section-heading news-analysis-heading">
            <div>
              <span className="news-eyebrow">FACTOR EXPLAINABILITY</span>
              <h2>详细分析</h2>
            </div>
            <span>{advice.factor_version} · 截至 {formatTime(advice.as_of)}</span>
          </div>

          <div className="news-analysis-grid">
            <div className="news-factor-breakdown">
              <h3>因子分解</h3>
              <p>各项为去重事件簇经过相关度、来源质量和时间衰减后的方向值。</p>
              <div className="news-component-grid">
                {Object.entries(componentMeta).map(([key, meta]) => {
                  const value = advice.components[key] ?? 0;
                  return (
                    <article className={`news-component-card tone-${toneForDirection(key === "negative_tail_risk" ? -value : value)}`} key={key}>
                      <div><span>{meta.label}</span><small>{meta.weight}</small></div>
                      <strong>{signed(value)}</strong>
                    </article>
                  );
                })}
              </div>
            </div>

            <aside className="news-risk-context">
              <h3>风险与行动约束</h3>
              <div className="news-context-row">
                <span>市场新闻环境</span>
                <StatusBadge tone={advice.market_regime.regime === "RISK_OFF" ? "negative" : advice.market_regime.regime === "CAUTION" ? "warning" : "neutral"}>{regimeText(advice.market_regime.regime)}</StatusBadge>
              </div>
              <p>{advice.market_regime.uncertainty}</p>
              <ul>
                {(advice.risk_flags.length ? advice.risk_flags : ["当前未识别额外风险否决项。"] ).map((item) => <li key={item}>{item}</li>)}
              </ul>
              <dl>
                <div><dt>最早可行动时间</dt><dd>{formatTime(advice.earliest_trade_at)}</dd></div>
                <div><dt>本次数据到期</dt><dd>{formatTime(advice.expires_at)}</dd></div>
              </dl>
            </aside>
          </div>

          <div className="news-event-section">
            <div className="news-subheading">
              <h3>关键事件簇</h3>
              <span>同一事件的转载只提升跨源可信度，不重复增加方向分</span>
            </div>
            {advice.events.length ? (
              <div className="news-event-grid">
                {advice.events.map((event) => (
                  <article className={`news-event-card border-${toneForDirection(event.direction)}`} key={event.cluster_id}>
                    <div className="news-event-meta">
                      <StatusBadge tone={toneForDirection(event.direction)}>{event.event_type}</StatusBadge>
                      {event.high_impact && <StatusBadge tone="warning">重大事件</StatusBadge>}
                    </div>
                    <h4>{event.title}</h4>
                    <p>{event.source_count} 个独立来源 · 贡献 {signed(event.contribution)}</p>
                    <dl>
                      <div><dt>发布时间</dt><dd>{formatTime(event.published_at)}</dd></div>
                      <div><dt>最早可行动</dt><dd>{formatTime(event.earliest_trade_at)}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            ) : (
              <div className="news-empty-state compact"><strong>没有合格的方向性事件簇</strong><span>通用 SEC 标题、规则回退或缺少时序信息的新闻只作为关注度证据。</span></div>
            )}
          </div>

          <div className="news-evidence-section">
            <div className="news-subheading">
              <h3>原始证据</h3>
              <span>保留来源、发布时间、模型方法和排除原因</span>
            </div>
            {advice.evidence.length ? (
              <div className="news-evidence-list">
                {advice.evidence.map((item) => (
                  <article key={`${item.id}-${item.published_at}`}>
                    <div className="news-evidence-state">
                      <StatusBadge tone={item.eligible ? toneForDirection(item.direction) : "neutral"}>{item.eligible ? item.direction : "未计分"}</StatusBadge>
                      <span>{item.method} · {item.event_type}</span>
                    </div>
                    <div className="news-evidence-copy">
                      <h4>{item.title}</h4>
                      <p>{item.publisher || item.source_id || item.source} · {formatTime(item.published_at)}</p>
                      {item.exclusion_reason && <small>{item.exclusion_reason}</small>}
                    </div>
                    {item.url ? <a href={item.url} target="_blank" rel="noreferrer" aria-label={`打开原文：${item.title}`}><ExternalLink size={15} /></a> : <span className="news-no-link">无链接</span>}
                  </article>
                ))}
              </div>
            ) : (
              <div className="news-empty-state compact"><strong>暂无原始证据</strong><span>系统不会在没有合格证据时生成方向性交易结论。</span></div>
            )}
          </div>
        </section>
      )}

      {newsQuery.error && <div className="error-banner news-page-error" role="alert">新闻列表加载失败：{newsQuery.error instanceof Error ? newsQuery.error.message : "未知错误"}</div>}
      {news?.warning && <div className="news-warning">{news.warning}</div>}

      <div className="news-company-stream">
        <NewsList title="公司新闻" caption={`${news?.company_items.length ?? 0} 条近期证据`} items={news?.company_items ?? []} />
      </div>

      <details className="news-diagnostics" open={false}>
        <summary>
          <div><span className="news-eyebrow">RESEARCH PIPELINE</span><strong>候选观察与数据模型状态</strong></div>
          <span>次级信息 · 点击展开</span>
        </summary>
        <div className="news-diagnostics-content">
          <section className="news-candidate-section">
            <div className="news-subheading">
              <div><h3>新闻因子候选观察</h3><span>{candidateQuery.data?.message || "需先生成当日快照"}</span></div>
              <button className="secondary-button" type="button" onClick={buildSnapshot} disabled={snapshotBusy}>{snapshotBusy ? "生成中" : "生成当日快照"}</button>
            </div>
            {snapshotError && <div className="news-inline-error" role="alert">{snapshotError}</div>}
            <div className="news-candidate-grid">
              {(candidateQuery.data?.candidates ?? []).map((candidate) => (
                <article key={candidate.symbol}>
                  <div><strong>{candidate.symbol}</strong><StatusBadge tone={candidate.tier === "FOCUS" ? "positive" : candidate.tier === "WATCH" ? "info" : "neutral"}>{candidate.tier}</StatusBadge></div>
                  <p>{candidate.research_state}</p>
                  <dl><div><dt>因子分数</dt><dd>{signed(candidate.news_score)}</dd></div><div><dt>文章数</dt><dd>{candidate.article_count}</dd></div></dl>
                </article>
              ))}
              {!candidateQuery.isLoading && !(candidateQuery.data?.candidates.length) && <div className="news-empty-state compact"><strong>暂无候选快照</strong><span>生成快照后仍需通过样本外验证，才可能产生行动标签。</span></div>}
            </div>
          </section>

          <section className="news-model-status">
            <div className="news-subheading"><h3>样本外验证</h3><StatusBadge tone={evaluation?.status === "VALIDATED" ? "positive" : "warning"}>{evaluation?.status || "检查中"}</StatusBadge></div>
            <p>{evaluation?.reason || "三个预测周期必须同时通过预设统计门槛。"}</p>
            <div className="news-validation-grid">
              {(evaluation?.horizons ?? []).map((item) => (
                <article key={item.horizon}>
                  <span>{item.horizon} 日超额收益</span>
                  <strong>{item.status}</strong>
                  <small>IC {item.spearman_ic?.toFixed(3) ?? "暂无"} · t {item.t_stat?.toFixed(2) ?? "暂无"} · OOS {item.walk_forward?.oos_sharpe_after_cost?.toFixed(2) ?? "暂无"}</small>
                </article>
              ))}
              {!(evaluation?.horizons.length) && <div className="news-empty-state compact"><strong>验证样本尚未形成</strong><span>当前建议固定为观望，总览新闻权重为 0。</span></div>}
            </div>
          </section>

          <section className="news-source-status">
            <div className="news-subheading"><h3>来源健康与白名单</h3><span>{healthQuery.data?.sources.filter((item) => item.availability === "AVAILABLE").length ?? 0} 个来源可用</span></div>
            <div className="news-source-grid">
              {(sourceQuery.data?.sources ?? []).filter((source) => source.scope === "COMPANY").map((source) => {
                const health = healthQuery.data?.sources.find((item) => item.source_id === source.source_id);
                const available = health?.availability === "AVAILABLE";
                return (
                  <article key={source.source_id}>
                    <div><strong>{source.display_name}</strong><StatusBadge tone={available ? "positive" : health?.availability === "UNAVAILABLE" ? "negative" : "neutral"}>{health?.availability || "NOT_CHECKED"}</StatusBadge></div>
                    <p>{source.scope} · {source.collector} · {source.authorization}</p>
                    <small>{health?.last_error || health?.availability_reason || `最近成功：${formatTime(health?.last_success_at)}`}</small>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      </details>
      </>}

      {activeTab === "market" && <section className="news-market-workspace" aria-label="宏观新闻">
        {marketQuery.error && <div className="error-banner news-page-error" role="alert">宏观新闻加载失败：{marketQuery.error instanceof Error ? marketQuery.error.message : "未知错误"}</div>}
        {marketQuery.data?.warning && <div className="news-warning">{marketQuery.data.warning}</div>}
        {marketQuery.isLoading ? <div className="market-headline-skeleton" aria-label="正在加载来源头条"><div /><div /><div /><div /><div /></div> : <HeadlineBoard groups={marketQuery.data?.headline_groups ?? []} activeSource={activeHeadlineSource} onSourceChange={setActiveHeadlineSource} onSelect={selectHeadline} status={marketQuery.data?.source_status ?? "UNAVAILABLE"} />}
        <div className={`news-market-overview panel posture-${radarQuery.data?.posture?.toLowerCase() ?? "neutral"}`}>
          <div><span className="news-eyebrow">US MARKET EVENT RADAR</span><h2>{radarQuery.data?.posture === "DEFENSIVE" ? "偏防御" : radarQuery.data?.posture === "CONSTRUCTIVE" ? "偏进攻" : "中性"}</h2><p>研究级市场姿态：事件传导和情景均可回链到公开来源，不构成交易指令。</p></div>
          <dl><div><dt>雷达置信度</dt><dd>{Math.round((radarQuery.data?.confidence ?? 0) * 100)}%</dd></div><div><dt>数据时间</dt><dd>{formatTime(marketQuery.data?.fetched_at)}</dd></div><div><dt>验证</dt><dd>{radarQuery.data?.validation.status || "检查中"}</dd></div></dl>
        </div>
        <OptionsMarketSummary onOpenOptions={onOpenOptions} />
        <section className="news-radar-scenarios panel"><div><span className="news-eyebrow">1–5 DAY SCENARIOS</span><h3>市场情景指引</h3></div>{(radarQuery.data?.scenarios ?? []).map((item) => <article key={item.kind}><strong>{item.kind}</strong><p>{item.text}</p></article>)}{radarQuery.data?.validation.reason && <small>{radarQuery.data.validation.reason}</small>}</section>
        <section className="news-radar-events">
          <div className="news-subheading"><div><h2>头条影响分析</h2><p>从来源头条提取影响路径与后续市场反应。</p></div><span>基于公开标题与 RSS 摘要</span></div>
          {selectedHeadlineId && !selectedEventId && <div className="news-warning">该头条暂未形成可审计的事件聚类，已定位到下方原始来源证据。</div>}
          {radarQuery.isLoading ? <div className="news-radar-skeleton" aria-label="正在加载关键事件"><div /><div /><div /></div> : radarEvents.length ? <div className="news-radar-event-list">{radarEvents.slice(0, eventVisibleCount).map((event) => <RadarEventCard event={event} onOpenOverview={onOpenOverview} selected={event.event_id === selectedEventId} key={event.event_id} />)}</div> : <div className="news-empty-state compact"><strong>当前没有可分析的关键事件</strong><span>数据源恢复或出现可审计主题后，分析会在这里显示。</span></div>}
          {eventVisibleCount < radarEvents.length && <button className="news-load-more news-radar-load-more" type="button" onClick={() => setEventVisibleCount((count) => count + 8)}>加载更多分析（已显示 {Math.min(eventVisibleCount, radarEvents.length)} / {radarEvents.length}）</button>}
        </section>
        <details className="news-raw-evidence" id="market-raw-evidence"><summary>查看原始宏观证据（最多 100 条）</summary><NewsList title="宏观新闻证据流" caption={`${marketQuery.data?.market_items.length ?? 0} 条市场资讯`} items={marketQuery.data?.market_items ?? []} pageSize={20} /></details>
        <details className="news-diagnostics" open={false}>
          <summary><div><span className="news-eyebrow">SOURCE HEALTH</span><strong>宏观新闻来源状态</strong></div><span>点击展开</span></summary>
          <div className="news-diagnostics-content"><section className="news-source-status"><div className="news-source-grid">
            {(sourceQuery.data?.sources ?? []).filter((source) => source.scope === "MARKET").map((source) => {
              const health = healthQuery.data?.sources.find((item) => item.source_id === source.source_id);
              const available = health?.availability === "AVAILABLE";
              return <article key={source.source_id}><div><strong>{source.display_name}</strong><StatusBadge tone={available ? "positive" : health?.availability === "UNAVAILABLE" ? "negative" : "warning"}>{health?.availability || "NOT_CHECKED"}</StatusBadge></div><p>{source.collector} · {source.authorization}</p><small>{health?.last_error || health?.availability_reason || `最近成功：${formatTime(health?.last_success_at)}`}</small></article>;
            })}
          </div></section></div>
        </details>
      </section>}
    </div>
  );
}
