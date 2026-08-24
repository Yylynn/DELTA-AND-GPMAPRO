import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { MarketCodeInput } from "@/components/MarketCodeInput";
import { PageHeader, StatusBadge } from "@/components/ui/workspace";
import { resolveMarketCode, type Market } from "@/lib/marketCode";

type Action = "BUY" | "ACCUMULATE" | "HOLD" | "REDUCE" | "SELL";
type Bias = "BULLISH" | "NEUTRAL" | "BEARISH";
type BadgeTone = "neutral" | "positive" | "warning" | "negative" | "info";

type SourceHealth = {
  source_id: string;
  display_name: string;
  scope: "COMPANY" | "MARKET";
  collector: string;
  status: "OK" | "DEGRADED" | "UNKNOWN";
  availability: "AVAILABLE" | "UNAVAILABLE" | "NOT_CHECKED";
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
};

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
};

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

function NewsList({ title, caption, items }: { title: string; caption: string; items: NewsItem[] }) {
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
          {items.slice(0, 10).map((item) => (
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

export function NewsCenter({ initialCode = "US.AAPL", initialDetailsOpen = false, contextKey = 0 }: Props) {
  const [market, setMarket] = useState<Market>(() => initialMarket(initialCode));
  const [ticker, setTicker] = useState(() => initialTicker(initialCode));
  const [code, setCode] = useState(initialCode.toUpperCase());
  const [refresh, setRefresh] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(initialDetailsOpen);
  const [inputError, setInputError] = useState<string | null>(null);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

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
    retry: 1,
  });
  const newsQuery = useQuery({
    queryKey: ["news", code, refresh],
    queryFn: () => fetchJson<NewsResponse>(`/api/news/${encodeURIComponent(code)}?limit=30&refresh=${refresh}`),
    retry: 1,
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
        void Promise.all([adviceQuery.refetch(), newsQuery.refetch()]);
      } else {
        setCode(nextCode);
        setRefresh(force);
      }
    } catch (error) {
      setInputError(error instanceof Error ? error.message : String(error));
    }
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
  const evaluation = evaluationQuery.data ?? advice.validation;
  const heroError = inputError || (adviceQuery.error instanceof Error ? adviceQuery.error.message : null);
  const validationTone: BadgeTone = advice.validation_status === "VALIDATED" ? "positive" : "warning";
  const sourceTone: BadgeTone = advice.status === "AVAILABLE" ? "positive" : advice.status === "STALE" ? "warning" : "negative";

  return (
    <div className="terminal-page news-decision-page">
      <PageHeader
        title="新闻中心"
        description="先看新闻建议，再按需核对因子、事件与原始证据。新闻仅用于研究辅助，不构成交易指令。"
        actions={(
          <form className="news-query-form" onSubmit={(event) => { event.preventDefault(); runQuery(false); }}>
            <MarketCodeInput market={market} value={ticker} onMarketChange={setMarket} onValueChange={setTicker} className="news-code-input" />
            <button className="secondary-button" type="submit">查询</button>
            <button className="primary-button news-refresh-button" type="button" onClick={() => runQuery(true)} disabled={adviceQuery.isFetching || newsQuery.isFetching}>
              <RefreshCw size={15} aria-hidden="true" />
              刷新新闻
            </button>
          </form>
        )}
      />

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

      <div className="news-stream-grid">
        <NewsList title="公司新闻" caption={`${news?.company_items.length ?? 0} 条近期证据`} items={news?.company_items ?? []} />
        <NewsList title="市场风险背景" caption="不直接混入公司方向分" items={news?.market_items ?? []} />
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
              {(sourceQuery.data?.sources ?? []).map((source) => {
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
    </div>
  );
}
