import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, InlineLoading, Tag, Theme } from "@carbon/react";
import {
  BarChart3,
  BellRing,
  ChevronLeft,
  Database,
  Gauge,
  Menu,
  Newspaper,
  Radar,
  Layers3,
  Settings2,
} from "lucide-react";
import { type ChartBar, type GpmaSeries } from "@/components/TerminalChart";
import { SkillDeltaChart } from "@/components/SkillDeltaChart";
import { MarketEvidence } from "@/components/MarketEvidence";
import { DecisionStateCard } from "@/components/DecisionStateCard";
import { ResearchDataset } from "@/components/ResearchDataset";
import { type Snapshot } from "@/components/FutuReconciliationPanel";
import { BacktestDataWorkspace } from "@/components/BacktestDataWorkspace";
import { MarketCodeInput } from "@/components/MarketCodeInput";
import { NewsCenter } from "@/components/NewsCenter";
import { OptionsRadar } from "@/components/OptionsRadar";
import { StockPool } from "@/components/StockPool";
import { resolveMarketCode, type Market } from "@/lib/marketCode";
import { SignalInterpretation } from "@/components/SignalInterpretation";
import {
  MetricCard,
  PageHeader,
  PanelHeading,
  StatusBadge,
} from "@/components/ui/workspace";

const request = async (path: string, options?: RequestInit) => {
  let response: Response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    response = await fetch(path, { ...options, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw new Error("请求超过 15 秒未返回；请检查网络连接后重试。");
    if (error instanceof TypeError)
      throw new Error(
        "无法连接本地后端（127.0.0.1:8014）。请运行 02_启动开发版.bat，并保持后端窗口开启。",
      );
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};
const bool = (value: boolean) => (value ? "✓" : "—");
type Action = "BUY" | "ACCUMULATE" | "HOLD" | "REDUCE" | "SELL";
type ActionTone = "positive" | "warning" | "negative" | "info";
type Interpretation = {
  action: Action;
  action_label: string;
  action_strength: number;
  position_guidance: string;
  next_steps: string[];
  as_of: string;
  drivers: Array<{ id: string; title: string; status: string; detail: string; date?: string | null }>;
  evidence: Array<{ source: string; direction: string; label: string; date: string; detail: string }>;
  missing_conditions: string[];
  blocked_by: string[];
  news_overlay: { status: string; bias: string; applied_points: number; effect: string; validation_status: string };
  validation: { status: string; message: string };
};
type OverviewNewsItem = {
  id: string;
  title: string;
  url: string | null;
  source: string;
  source_id?: string;
  publisher?: string;
  published_at: string | null;
  summary: string | null;
};
type OverviewNewsResponse = {
  company_items: OverviewNewsItem[];
  source_status: string;
  warning: string | null;
  fetched_at: string | null;
};
type GpmaSnapshot = {
  trend: {
    direction: string;
    strength: string;
    bull_bg: boolean;
    bull_strong: boolean;
    bear_bg: boolean;
  };
  volume: {
    current: number;
    ma20: number;
    ratio: number | null;
    vol_ok: boolean;
    vol_strong: boolean;
  };
  filters: { gap_rate: number | null; gap_ok: boolean; range_ok: boolean };
  signals: Record<string, boolean>;
  divergence: Record<string, boolean>;
  as_of: string;
};
type VolumeSnapshot = {
  as_of: string;
  latest_volume: number;
  volume_ma20: number;
  relative_volume: number;
  volume_level: string;
  volume_trend: string;
  volume_anomaly: string;
  price_volume_context: string;
  data: { freshness: string; latest_bar_date: string };
};
const actionTone = (action?: Action): ActionTone =>
  action === "BUY" || action === "ACCUMULATE"
    ? "positive"
    : action === "HOLD"
      ? "warning"
      : action === "REDUCE" || action === "SELL"
        ? "negative"
        : "info";
const directionTone = (direction?: string): ActionTone =>
  direction === "BULLISH" ? "positive" : direction === "BEARISH" ? "negative" : "info";

type AlertIndicator = {
  id: "vix" | "vxn" | "vvix" | "vixy";
  label: string;
  code: string;
  watch_level: number | null;
  risk_level: number | null;
};
type MarketTechnicalSignal = {
  id: string;
  category: "GPMAPRO_TECHNICAL";
  asset_type?: "VOLATILITY" | "MARKET_INDEX";
  label: string;
  code?: string;
  signal_code: string;
  signal_direction: string;
  signal_date: string;
  display_label: string;
  message: string;
  read: boolean;
};
type MarketAlert = {
  id: string;
  label: string;
  date: string;
  severity: "WATCH" | "RISK";
  message: string;
  read: boolean;
  category?: string;
  signal_code?: string;
  display_label?: string;
};
type MarketAlertSnapshot = {
  config: { change_threshold_pct: number; indicators: AlertIndicator[] };
  observations: Array<{
    id: string;
    label: string;
    code: string;
    source?: string;
    date: string;
    close: number;
    change_pct: number;
    severity: string;
    reasons: Array<{ message: string }>;
  }>;
  alerts: MarketAlert[];
  risk_score?: number;
  regime?: "NORMAL" | "WATCH" | "RISK" | "CRISIS";
  risk_transition?: string;
  modules?: Array<{
    id: string;
    label: string;
    score: number | null;
    weight: number;
    status: "AVAILABLE" | "UNAVAILABLE";
    evidence: Array<{ label: string; message: string; percentile?: number | null }>;
  }>;
  evidence?: Array<{ module: string; label: string; message: string }>;
  data_health?: { status: string; available_modules: number; total_modules: number; failures: Array<{ label: string; error: string; fallback?: string; cache_age_seconds?: number }>; sources: string[]; providers?: Record<string, { status: string; configured: boolean; as_of?: string; error?: string }> };
  risk_history?: Array<{ date: string; risk_score: number; regime: string; available_modules: number }>;
  active_alerts?: MarketAlert[];
  technical_signals?: MarketTechnicalSignal[];
  market_index_technical_signals?: MarketTechnicalSignal[];
  market_index_technical_indicators?: Array<{
    id: string;
    label: string;
    code: string;
  }>;
  market_index_last_check?: Array<{
    id: string;
    label: string;
    code: string;
    source: string;
    date: string;
    checked_at: string;
  }>;
  technical_lookback_sessions?: number;
  last_check: {
    checked_at: string;
    status: string;
    failures: Array<{ label: string; error: string }>;
  } | null;
};

function MarketAlertMarquee({ message }: { message: string }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLSpanElement>(null);
  const [metrics, setMetrics] = useState({ overflow: false, distance: 0, duration: 0 });

  useEffect(() => {
    const updateMetrics = () => {
      const viewportWidth = viewportRef.current?.clientWidth ?? 0;
      const messageWidth = messageRef.current?.scrollWidth ?? 0;
      const overflow = messageWidth > viewportWidth;
      const distance = overflow ? messageWidth + 48 : 0;
      const duration = overflow ? Math.max(18, distance / 42) : 0;
      setMetrics((current) => current.overflow === overflow && current.distance === distance
        ? current
        : { overflow, distance, duration });
    };
    updateMetrics();
    const observer = new ResizeObserver(updateMetrics);
    if (viewportRef.current) observer.observe(viewportRef.current);
    if (messageRef.current) observer.observe(messageRef.current);
    return () => observer.disconnect();
  }, [message]);

  const style = {
    "--market-alert-marquee-distance": `${metrics.distance}px`,
    "--market-alert-marquee-duration": `${metrics.duration}s`,
  } as CSSProperties;

  return (
    <div
      ref={viewportRef}
      className={`market-alert-marquee${metrics.overflow ? " is-moving" : ""}`}
      aria-label={`当前预警详情：${message}`}
      tabIndex={metrics.overflow ? 0 : undefined}
      title={message}
    >
      <div className="market-alert-marquee-track" style={style}>
        <span ref={messageRef} className="market-alert-marquee-message">{message}</span>
        {metrics.overflow && <span className="market-alert-marquee-message market-alert-marquee-copy" aria-hidden="true">{message}</span>}
      </div>
    </div>
  );
}

function MarketAlertBanner({
  data,
  onCheck,
  checking,
  error,
}: {
  data?: MarketAlertSnapshot;
  onCheck: () => void;
  checking: boolean;
  error: string | null;
}) {
  const unread = (data?.active_alerts ?? data?.alerts ?? []).filter(
    (item) => !item.read,
  );
  const threshold = data?.config.change_threshold_pct ?? 3;
  const latestReadings = (data?.config.indicators ?? []).map((indicator) => ({
    indicator,
    reading: data?.observations
      .slice()
      .reverse()
      .find((item) => item.id === indicator.id),
  }));
  const highest = data?.regime === "CRISIS" ? "RISK" : data?.regime === "RISK" ? "RISK" : data?.regime === "WATCH" ? "WATCH" : unread.some((item) => item.severity === "RISK")
    ? "RISK"
    : unread.length
      ? "WATCH"
      : "NORMAL";
  const action = (
    <Button kind="ghost" size="sm" onClick={onCheck} disabled={checking}>
      {checking ? <InlineLoading description="刷新中" /> : "立即刷新"}
    </Button>
  );
  const hasElevatedRisk = Boolean(
    unread.length || (data?.regime && data.regime !== "NORMAL"),
  );
  const message = error
    ? `刷新失败：${error}`
    : data?.regime && data.regime !== "NORMAL"
      ? `综合评分 ${data.risk_score ?? "未计算"}/100；${data.risk_transition ?? "风险状态更新"}；${data.evidence?.[0]?.label ?? "跨资产模块"}：${data.evidence?.[0]?.message ?? "等待证据"}`
      : unread.length
        ? unread.map((item) => `${item.label}：${item.message}`).join("；")
        : `综合评分 ${data?.risk_score ?? "未计算"}/100；当前指标未触发关注或高风险条件`;
  const bannerTone = error ? "watch" : hasElevatedRisk ? highest.toLowerCase() : "normal";
  const title = data?.regime === "CRISIS"
    ? "市场危机状态"
    : highest === "RISK"
      ? "市场高风险预警"
      : "市场波动预警";
  return (
    <div className={`market-alert-banner ${bannerTone}`}>
      <BellRing size={16} />
      <div className="market-alert-body">
        <div className="market-alert-summary">
          <b>{title}</b>
          <MarketAlertMarquee message={message} />
        </div>
        <div className="market-alert-indicators" aria-label="当前波动率指标与触发条件">
          <span className="market-alert-rule">
            单日上涨 ≥ {threshold.toFixed(1)}%：显示“关注”
          </span>
          {latestReadings.map(({ indicator, reading }) => {
            const tone = reading?.severity === "RISK"
              ? "risk"
              : reading?.severity === "WATCH"
                ? "watch"
                : reading
                  ? "normal"
                  : "pending";
            const levelRule = indicator.watch_level == null
              ? `涨幅阈值 ${threshold.toFixed(1)}%`
              : `关注 ≥ ${indicator.watch_level} / 高风险 ≥ ${indicator.risk_level}`;
            return (
              <span
                className={`market-alert-indicator ${tone}`}
                key={indicator.id}
                title={`${indicator.label}：${levelRule}`}
              >
                <b>{indicator.label}</b>
                <span>{reading ? reading.close.toFixed(2) : "待刷新"}</span>
                {reading && (
                  <span className="market-alert-change">
                    {reading.change_pct >= 0 ? "+" : ""}{reading.change_pct.toFixed(2)}%
                  </span>
                )}
                <small>{reading?.severity === "RISK" ? "高风险" : reading?.severity === "WATCH" ? "关注" : reading ? "正常" : levelRule}</small>
              </span>
            );
          })}
        </div>
      </div>
      {action}
    </div>
  );
}

function OverviewIndicators({
  gpma,
  volume,
  gpmaLoading,
  volumeLoading,
  gpmaError,
  volumeError,
}: {
  gpma?: GpmaSnapshot;
  volume?: VolumeSnapshot;
  gpmaLoading: boolean;
  volumeLoading: boolean;
  gpmaError?: string;
  volumeError?: string;
}) {
  const activeSignals = Object.entries(gpma?.signals ?? {})
    .filter(([, active]) => active)
    .map(([name]) => name.toUpperCase());
  const activeDivergences = Object.entries(gpma?.divergence ?? {})
    .filter(([, active]) => active)
    .map(([name]) => name.replaceAll("_", " ").toUpperCase());
  const gpmaStatus = gpmaLoading
    ? "正在计算 GPMAPRO 指标。"
    : gpmaError
      ? `GPMAPRO 指标暂不可用：${gpmaError}`
      : !gpma
        ? "当前快照没有可用的 GPMAPRO 指标。"
        : null;
  const volumeStatus = volumeLoading
    ? "正在计算成交量指标。"
    : volumeError
      ? `成交量指标暂不可用：${volumeError}`
      : !volume
        ? "当前快照没有可用的成交量指标。"
        : null;
  return (
    <section className="command-indicators" aria-label="当前技术指标">
      <article className="command-indicator-panel panel panel-evidence">
        <div className="command-panel-heading">
          <div><span>技术指标</span><h2>GPMAPRO 当前状态</h2></div>
          <StatusBadge tone={gpma ? directionTone(gpma.trend.direction) : "neutral"}>
            {gpma?.as_of ?? "等待数据"}
          </StatusBadge>
        </div>
        {gpmaStatus && <p className="command-indicator-state">{gpmaStatus}</p>}
        <div className="command-indicator-metrics">
          <div><span>趋势</span><b>{gpma ? `${gpma.trend.direction} / ${gpma.trend.strength}` : "等待计算"}</b></div>
          <div><span>成交量倍数</span><b>{gpma?.volume.ratio == null ? "等待计算" : `${gpma.volume.ratio.toFixed(2)}x`}</b></div>
          <div><span>Gap 过滤器</span><b>{gpma ? (gpma.filters.gap_ok ? "通过" : "未通过") : "等待计算"}</b></div>
          <div><span>Range 过滤器</span><b>{gpma ? (gpma.filters.range_ok ? "通过" : "未通过") : "等待计算"}</b></div>
        </div>
        <div className="command-indicator-signals">
          <div><span>B/S 信号</span><b>{activeSignals.join(" / ") || (gpma ? "当前无触发" : "等待计算")}</b></div>
          <div><span>背离</span><b>{activeDivergences.join(" / ") || (gpma ? "当前无触发" : "等待计算")}</b></div>
        </div>
      </article>
      <article className="command-indicator-panel panel panel-research">
        <div className="command-panel-heading">
          <div><span>量能确认</span><h2>成交量监控</h2></div>
          <StatusBadge tone={volume?.data.freshness === "FRESH" ? "positive" : volume ? "warning" : "neutral"}>
            {volume?.data.freshness ?? "等待数据"}
          </StatusBadge>
        </div>
        {volumeStatus && <p className="command-indicator-state">{volumeStatus}</p>}
        <div className="command-indicator-metrics command-volume-metrics">
          <div><span>RVOL</span><b>{volume ? `${volume.relative_volume.toFixed(2)}x` : "等待计算"}</b></div>
          <div><span>成交量状态</span><b>{volume?.volume_level ?? "等待计算"}</b></div>
          <div><span>短期趋势</span><b>{volume?.volume_trend ?? "等待计算"}</b></div>
          <div><span>异常</span><b>{volume?.volume_anomaly ?? "等待计算"}</b></div>
          <div><span>最新成交量</span><b>{volume?.latest_volume.toLocaleString() ?? "等待计算"}</b></div>
          <div><span>20D Avg</span><b>{volume?.volume_ma20.toLocaleString() ?? "等待计算"}</b></div>
        </div>
        <p className="command-indicator-context">{volume?.price_volume_context ?? "等待成交量上下文。"}</p>
      </article>
    </section>
  );
}

function MarketVolatilityAlerts({
  data,
  onCheck,
  checking,
  refresh,
}: {
  data?: MarketAlertSnapshot;
  onCheck: () => void;
  checking: boolean;
  refresh: () => Promise<unknown>;
}) {
  const [draft, setDraft] = useState<MarketAlertSnapshot["config"] | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  const [checkingProviders, setCheckingProviders] = useState(false);
  const [providerMessage, setProviderMessage] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (data?.config) setDraft(data.config);
  }, [data?.config]);
  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setMessage(null);
    try {
      await request("/api/market-volatility-alerts/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      await refresh();
      setMessage("预警配置已保存。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };
  const checkProviders = async () => {
    setCheckingProviders(true); setProviderMessage(null);
    try {
      const result = await request("/api/market-volatility-alerts/providers/check", { method: "POST" });
      const providers = result.providers as Record<string, { status: string }>;
      setProviderMessage(Object.entries(providers).map(([name, provider]) => `${name}：${provider.status}`).join(" · "));
      await refresh();
    } catch (error) {
      setProviderMessage(error instanceof Error ? error.message : String(error));
    } finally { setCheckingProviders(false); }
  };
  const readings = data?.observations.slice(-4).reverse() ?? [];
  const technicalSignals = (data?.technical_signals ?? [])
    .slice()
    .reverse()
    .slice(0, 20);
  const indexTechnicalSignals = (data?.market_index_technical_signals ?? [])
    .slice()
    .reverse()
    .slice(0, 20);
  const technicalDays = data?.technical_lookback_sessions ?? 3;
  const indexChecks = new Map(
    (data?.market_index_last_check ?? []).map((item) => [item.id, item]),
  );
  const indexFailures = new Map(
    (data?.last_check?.failures ?? []).map((item) => [item.label, item.error]),
  );
  const priorityAlerts = (data?.active_alerts ?? data?.alerts ?? [])
    .slice()
    .sort((left, right) =>
      Number(right.severity === "RISK") - Number(left.severity === "RISK") ||
      right.date.localeCompare(left.date),
    );
  const regime = data?.regime ?? (priorityAlerts.some((item) => item.severity === "RISK")
    ? "RISK"
    : priorityAlerts.length
      ? "WATCH"
      : "NORMAL");
  const regimeLabel = { NORMAL: "正常", WATCH: "重点观察", RISK: "高风险", CRISIS: "危机" }[regime];
  return (
    <div className="terminal-page">
      <PageHeader
        title="市场风险雷达"
        description="Yahoo Finance 公开日线风险雷达；启动和手动刷新时联网，不生成交易指令。"
        actions={
          <button
            className="primary-button"
            onClick={onCheck}
            disabled={checking}
          >
            {checking ? "刷新中…" : "立即刷新"}
          </button>
        }
      />
      {message && (
        <p
          className={
            message.includes("已保存") ? "success-banner" : "error-banner"
          }
        >
          {message}
        </p>
      )}
      <section className={`risk-command panel panel-risk ${regime === "CRISIS" ? "risk" : regime.toLowerCase()}`}>
        <div>
          <span>综合市场风险状态</span>
          <strong>{regimeLabel}</strong>
          <p>{data?.risk_transition ?? "等待首次检查"} · {data?.evidence?.[0]?.message ?? priorityAlerts[0]?.message ?? "最近一次检查未发现需要优先处理的市场风险事件。"}</p>
        </div>
        <div className="risk-command-metrics">
          <div><span>风险评分</span><b>{data?.risk_score ?? "—"} / 100</b></div>
          <div><span>活跃预警</span><b>{priorityAlerts.length}</b></div>
          <div><span>数据健康</span><b>{data?.data_health?.status ?? data?.last_check?.status ?? "等待刷新"}</b></div>
        </div>
      </section>
      <section className="panel panel-evidence mb-4 p-4">
        <PanelHeading title="跨资产压力分解" description="模块内取最强证据，跨模块共振后才升级风险状态" meta={`${data?.data_health?.available_modules ?? 0}/${data?.data_health?.total_modules ?? 5} 个模块可用`} />
        <div className="grid grid-cols-5 gap-3 text-sm">
          {(data?.modules ?? []).map((module) => (
            <article className="rounded border border-zinc-800 p-3" key={module.id}>
              <span className="block text-xs text-zinc-500">{module.label}</span>
              <b className="mt-1 block text-lg">{module.score == null ? "数据不可用" : `${module.score} / 100`}</b>
              <p className="mt-2 text-xs text-zinc-400">{module.evidence[0]?.label ?? "等待数据"} · {module.evidence[0]?.message ?? "—"}</p>
            </article>
          ))}
        </div>
        {data?.risk_history?.length ? <p className="mt-3 text-xs text-zinc-500">最近风险轨迹：{data.risk_history.map((item) => `${item.date.slice(5)} ${item.risk_score}`).join(" · ")}</p> : null}
        <div className="mt-3 flex items-center gap-3 text-xs text-zinc-500"><span>数据源：{Object.entries(data?.data_health?.providers ?? {}).map(([name, provider]) => `${name} ${provider.status}`).join(" · ") || "等待检查"}</span><button className="secondary-button" onClick={() => void checkProviders()} disabled={checkingProviders}>{checkingProviders ? "检查中…" : "检查数据源"}</button></div>
        {providerMessage ? <p className="mt-2 text-xs text-zinc-400">{providerMessage}</p> : null}
        {data?.data_health?.failures?.length ? <p className="mt-2 text-xs text-amber-300">部分数据不可用：{data.data_health.failures.map((item) => `${item.label}${item.fallback ? "（使用陈旧缓存）" : ""}`).join("、")}</p> : null}
      </section>
      <section className="panel panel-evidence p-4">
        <PanelHeading
          title="指标与触发线"
          description="自定义风险指标、数据代码与触发阈值"
          meta="Yahoo Finance · 5 分钟本地缓存"
        />
        {draft && (
          <>
            <div className="grid grid-cols-5 gap-3 text-xs text-zinc-400">
              <span>指标</span>
              <span>Yahoo Finance 代码</span>
              <span>关注 / 高风险</span>
              <span>单日涨幅</span>
              <span>说明</span>
            </div>
            {draft.indicators.map((item, index) => (
              <div
                className="grid grid-cols-5 items-center gap-3 border-t border-zinc-800 py-3"
                key={item.id}
              >
                <b>{item.label}</b>
                <input
                  className="terminal-input"
                  value={item.code}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      indicators: draft.indicators.map((entry, i) =>
                        i === index
                          ? { ...entry, code: e.target.value.toUpperCase() }
                          : entry,
                      ),
                    })
                  }
                />
                <span className="text-xs text-zinc-400">
                  {item.watch_level == null
                    ? "—"
                    : `${item.watch_level} / ${item.risk_level}`}
                </span>
                <span className="text-xs text-zinc-400">
                  ≥ {draft.change_threshold_pct}%
                </span>
                <span className="text-xs text-zinc-500">
                  {item.id === "vixy"
                    ? "短期期货 ETF"
                    : item.id === "vvix"
                      ? "VIX 的隐含波动率"
                      : "隐含波动率"}
                </span>
              </div>
            ))}
            <div className="mt-3 flex items-end gap-3 border-t border-zinc-800 pt-3">
              <label className="text-xs text-zinc-400">
                单日上涨阈值
                <input
                  className="terminal-input mt-1 w-24"
                  type="number"
                  min="0.1"
                  max="100"
                  step="0.1"
                  value={draft.change_threshold_pct}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      change_threshold_pct: Number(e.target.value),
                    })
                  }
                />
              </label>
              <button
                className="primary-button"
                onClick={() => void save()}
                disabled={saving}
              >
                {saving ? "校验中…" : "保存并校验"}
              </button>
            </div>
          </>
        )}
      </section>
      <section className="panel panel-evidence mt-4 overflow-hidden">
        <div className="panel-title p-4 pb-0">最近观测</div>
        <table>
          <thead>
            <tr>
              <th>指标</th>
              <th>收盘</th>
              <th>日涨跌</th>
              <th>日期</th>
              <th>状态</th>
              <th>触发原因</th>
            </tr>
          </thead>
          <tbody>
            {readings.map((item) => (
              <tr key={`${item.id}-${item.date}`}>
                <td>
                  {item.label}
                  <span className="block text-xs text-zinc-500">
                    {item.code} · {item.source}
                  </span>
                </td>
                <td>{item.close.toFixed(2)}</td>
                <td
                  className={
                    item.change_pct >= 3 ? "text-rose-300" : "text-zinc-300"
                  }
                >
                  {item.change_pct >= 0 ? "+" : ""}
                  {item.change_pct.toFixed(2)}%
                </td>
                <td>{item.date}</td>
                <td>{item.severity}</td>
                <td>
                  {item.reasons.map((reason) => reason.message).join("；") ||
                    "—"}
                </td>
              </tr>
            ))}
            {!readings.length && (
              <tr>
                <td colSpan={6} className="text-zinc-500">
                  尚未刷新。联网后点击“立即刷新”。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      <section className="panel panel-research mt-4 overflow-hidden">
        <div className="panel-title p-4 pb-0">
          波动率 GPMAPRO 技术信号{" "}
          <span className="float-right text-xs font-normal text-zinc-500">
            仅收盘确认 · 最近 {technicalDays} 个交易日补漏
          </span>
        </div>
        <p className="px-4 pt-2 text-xs text-zinc-400">
          B1–B3 = 波动率上行；S1–S2 = 波动率下行；顶部/底部笑脸及箭头 =
          背离观察点。均非交易指令。
        </p>
        <table>
          <thead>
            <tr>
              <th>指标</th>
              <th>日期</th>
              <th>图形信号</th>
              <th>方向含义</th>
            </tr>
          </thead>
          <tbody>
            {technicalSignals.map((item) => (
              <tr key={item.id}>
                <td>{item.label}</td>
                <td>{item.signal_date}</td>
                <td>{item.signal_code}</td>
                <td>{item.display_label}</td>
              </tr>
            ))}
            {!technicalSignals.length && (
              <tr>
                <td colSpan={4} className="text-zinc-500">
                  最近 {technicalDays} 个交易日暂无新的最终图形信号。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      <section className="panel panel-research mt-4 overflow-hidden">
        <div className="panel-title p-4 pb-0">
          市场指数技术信号{" "}
          <span className="float-right text-xs font-normal text-zinc-500">
            仅收盘确认 · 最近 {technicalDays} 个交易日
          </span>
        </div>
        <p className="px-4 pt-2 text-xs text-zinc-400">
          监控标普 500（^GSPC）、纳斯达克
          100（^NDX）与纳斯达克综合指数（^IXIC）。仅提示最终图形观察点，不使用波动率阈值或单日涨幅规则。
        </p>
        <table>
          <thead>
            <tr>
              <th>指数</th>
              <th>Yahoo 代码</th>
              <th>最近检查日</th>
              <th>图形信号</th>
              <th>状态 / 含义</th>
            </tr>
          </thead>
          <tbody>
            {(data?.market_index_technical_indicators ?? []).map(
              (indicator) => {
                const check = indexChecks.get(indicator.id);
                const signals = indexTechnicalSignals.filter(
                  (item) => item.label === indicator.label,
                );
                const failure = indexFailures.get(indicator.label);
                return (
                  <tr key={indicator.id}>
                    <td>{indicator.label}</td>
                    <td>{indicator.code}</td>
                    <td>
                      {check?.date ?? "—"}
                      <span className="block text-xs text-zinc-500">
                        {check?.source ?? (failure ? "刷新失败" : "待刷新")}
                      </span>
                    </td>
                    <td>
                      {signals.map((item) => item.signal_code).join(" · ") ||
                        "—"}
                    </td>
                    <td className={failure ? "text-rose-300" : "text-zinc-300"}>
                      {failure
                        ? failure
                        : signals
                            .map((item) => item.display_label)
                            .join("；") ||
                          `最近 ${technicalDays} 日无最终图形信号`}
                    </td>
                  </tr>
                );
              },
            )}
          </tbody>
        </table>
      </section>
      <section className="panel panel-risk mt-4 overflow-hidden">
        <div className="panel-title p-4 pb-0">
          预警历史{" "}
          <span className="float-right text-xs font-normal text-zinc-500">
            含超出当前窗口的旧记录
          </span>
        </div>
        <table>
          <thead>
            <tr>
              <th>等级</th>
              <th>指标</th>
              <th>交易日</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            {(data?.alerts ?? [])
              .slice()
              .reverse()
              .slice(0, 20)
              .map((item) => (
                <tr key={item.id}>
                  <td
                    className={
                      item.severity === "RISK"
                        ? "text-rose-300"
                        : "text-amber-300"
                    }
                  >
                    {item.severity}
                  </td>
                  <td>{item.label}</td>
                  <td>{item.date}</td>
                  <td>{item.message}</td>
                </tr>
              ))}
            {!(data?.alerts ?? []).length && (
              <tr>
                <td colSpan={4} className="text-zinc-500">
                  暂无预警记录。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function marketForCode(code: string): Market {
  const normalized = code.toUpperCase();
  if (normalized.startsWith("HK.")) return "HK";
  if (normalized.startsWith("SH.") || normalized.startsWith("SZ.")) return "A";
  return "US";
}

function Overview({
  onOpenNews,
  riskData,
  initialCode = "US.VXN",
  contextKey = 0,
}: {
  onOpenNews: (symbol: string) => void;
  riskData?: MarketAlertSnapshot;
  initialCode?: string;
  contextKey?: number;
}) {
  const [symbol, setSymbol] = useState(initialCode);
  const [draft, setDraft] = useState(initialCode);
  const [market, setMarket] = useState<Market>(() => marketForCode(initialCode));
  const [timeframe, setTimeframe] = useState("1d");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<
    string | undefined
  >();
  const [focusDate, setFocusDate] = useState<string | undefined>();
  const [showFullDecision, setShowFullDecision] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<{
    snapshot_id: string;
    code: string;
    bar_count: number;
    end_date?: string;
  } | null>(null);
  const autoFetchKey = useRef(-1);
  const snapshots = useQuery<{ snapshots: Snapshot[] }>({
    queryKey: ["market-snapshots"],
    queryFn: () => request("/api/data/market/snapshots"),
    retry: false,
  });
  // Most research snapshots are daily so that EMA250 has full warm-up.  A
  // weekly/monthly chart must fall back to that same daily snapshot and let
  // the backend resample it; otherwise changing the selector disables every
  // query unless a separate native weekly/monthly snapshot was fetched.
  const matchingSnapshots =
    snapshots.data?.snapshots.filter(
      (item) =>
        item.code === symbol && item.autype === "QFQ" && item.bar_count > 0,
    ) ?? [];
  const discoveredSnapshot = matchingSnapshots.find(
    (item) => item.timeframe === "1d",
  )?.snapshot_id;
  const snapshotId = selectedSnapshotId ?? discoveredSnapshot;
  const snapshotQuery = snapshotId
    ? `&snapshot_id=${encodeURIComponent(snapshotId)}`
    : "";
  const refresh = async (requestedCode?: string) => {
    let code: string;
    try {
      code = requestedCode ? requestedCode.toUpperCase() : resolveMarketCode(draft, market);
    } catch (error) {
      setFetchError(error instanceof Error ? error.message : String(error));
      return;
    }
    setFetching(true);
    setFetchError(null);
    try {
      const created = await request("/api/data/market/snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          timeframe: "1d",
          adjustment: "adjusted",
          start: "2018-01-01",
        }),
      });
      setSymbol(code);
      setDraft(code);
      setSelectedSnapshotId(created.snapshot_id);
      setLastFetch(created);
      await snapshots.refetch();
    } catch (error) {
      setFetchError(error instanceof Error ? error.message : String(error));
    } finally {
      setFetching(false);
    }
  };
  useEffect(() => {
    if (contextKey === 0) return;
    const code = initialCode.toUpperCase();
    setSymbol(code);
    setDraft(code);
    setMarket(marketForCode(code));
    setSelectedSnapshotId(undefined);
    setFocusDate(undefined);
    setLastFetch(null);
  }, [contextKey]);
  useEffect(() => {
    if (contextKey === 0 || snapshots.isLoading || autoFetchKey.current === contextKey) return;
    autoFetchKey.current = contextKey;
    if (!discoveredSnapshot) void refresh(initialCode.toUpperCase());
  }, [contextKey, discoveredSnapshot, initialCode, snapshots.isLoading]);
  const bars = useQuery<{
    bars: Array<Omit<ChartBar, "time"> & { date: string }>;
  }>({
    queryKey: ["bars", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(
        `/api/data/market/snapshots/${snapshotId}/ohlcv?timeframe=${timeframe}`,
      ),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const itd = useQuery<any>({
    queryKey: ["itd", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(`/api/itd/${symbol}?timeframe=${timeframe}${snapshotQuery}`),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const gpma = useQuery<GpmaSnapshot>({
    queryKey: ["gpmapro", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(`/api/gpmapro/${symbol}?timeframe=${timeframe}${snapshotQuery}`),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const series = useQuery<{ series: GpmaSeries[] }>({
    queryKey: ["gpmapro-series", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(
        `/api/gpmapro/${symbol}/series?timeframe=${timeframe}${snapshotQuery}`,
      ),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const gpma2 = useQuery<{
    series: GpmaSeries[];
    calculation_source: "local_gpmaapro_v1";
    reconciliation_status: "not_reconciled" | "matched" | "drift";
  }>({
    queryKey: ["gpma2-series", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(
        `/api/gpma2/${symbol}/series?timeframe=${timeframe}${snapshotQuery}`,
      ),
    enabled: Boolean(snapshotId && timeframe === "1d"),
    retry: false,
  });
  const volume = useQuery<VolumeSnapshot>({
    queryKey: ["volume", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(`/api/volume/${symbol}?timeframe=${timeframe}${snapshotQuery}`),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const interpretation = useQuery<Interpretation>({
    queryKey: ["signal-interpretation-current", symbol, timeframe, snapshotId],
    queryFn: () => request(`/api/interpretation/${encodeURIComponent(symbol)}?timeframe=${timeframe}${snapshotQuery}&include_audit=false`),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const companyNews = useQuery<OverviewNewsResponse>({
    // Match the NewsCenter cache key for its initial refresh state.
    queryKey: ["news", symbol, 0],
    queryFn: () => request(`/api/news/${encodeURIComponent(symbol)}?limit=6&refresh=false`),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const chartBars = (bars.data?.bars ?? []).map((bar) => ({
    ...bar,
    time: bar.date,
  }));
  const state = gpma.data;
  const action = interpretation.data;
  const latestBar = chartBars.at(-1);
  const previousBar = chartBars.at(-2);
  const priceChange = latestBar && previousBar ? latestBar.close - previousBar.close : null;
  const priceChangePct = priceChange != null && previousBar?.close ? (priceChange / previousBar.close) * 100 : null;
  const activeAlerts = (riskData?.active_alerts ?? riskData?.alerts ?? [])
    .slice()
    .sort((left, right) => Number(right.severity === "RISK") - Number(left.severity === "RISK") || right.date.localeCompare(left.date));
  const actionBlocked = [...(action?.blocked_by ?? []), ...(action?.missing_conditions ?? [])].filter(Boolean);
  const newsItems = companyNews.data?.company_items ?? [];
  return (
    <div className="terminal-page overview-page">
      <header className="overview-toolbar">
        <div className="overview-toolbar-title">
          <span>DELTA · RESEARCH WORKSPACE</span>
          <strong>总览</strong>
        </div>
        <form
          className="overview-toolbar-actions"
          onSubmit={(event) => {
            event.preventDefault();
            void refresh();
          }}
        >
          <span className="overview-toolbar-status">
            {fetching
              ? "行情拉取中…"
              : `Latest Bar ${volume.data?.data.latest_bar_date ?? "—"}`}
          </span>
          <MarketCodeInput
            market={market}
            value={draft}
            onMarketChange={setMarket}
            onValueChange={setDraft}
            className="overview-code-input"
          />
          <select
            className="terminal-input"
            value={timeframe}
            onChange={(event) => {
              setTimeframe(event.target.value);
              setSelectedSnapshotId(undefined);
              setFocusDate(undefined);
            }}
          >
            <option value="1d">日线</option>
            <option value="1w">周线</option>
            <option value="1mo">月线</option>
          </select>
          <button className="primary-button" disabled={fetching} type="submit">
            {fetching ? "拉取中" : "拉取"}
          </button>
        </form>
      </header>
      {fetchError && (
        <p className="error-banner mb-3">行情拉取失败：{fetchError}</p>
      )}
      {lastFetch && (
        <p className="mb-3 text-xs text-emerald-300">
          已切换至 {lastFetch.code} · {lastFetch.bar_count} bars · 快照{" "}
          {lastFetch.snapshot_id}
        </p>
      )}
      {!snapshotId ? (
        <section className="empty-state panel panel-evidence"><strong>尚未找到 {symbol} 的可用行情快照</strong><span>使用右上角“拉取”创建不可变市场快照后，系统才会显示 K 线、行动建议与研究证据。</span></section>
      ) : (
        <div className="command-center">
          <div className="command-layout">
            <main className="command-main">
              <section className="command-chart panel panel-evidence">
                <div className="command-market-header">
                  <div><span>研究标的</span><strong>{symbol}</strong><small>{timeframe.toUpperCase()} · {snapshotId.slice(0, 18)}</small></div>
                  <div className={priceChange != null && priceChange < 0 ? "is-negative" : "is-positive"}><span>最新收盘</span><b>{latestBar?.close.toFixed(2) ?? "—"}</b><small>{priceChange == null ? "等待 K 线" : `${priceChange >= 0 ? "+" : ""}${priceChange.toFixed(2)} · ${priceChangePct?.toFixed(2)}%`}</small></div>
                  <div><span>成交量</span><b>{latestBar?.volume.toLocaleString() ?? "—"}</b><small>数据截至 {volume.data?.data.latest_bar_date ?? "—"}</small></div>
                </div>
                <SkillDeltaChart
                  bars={chartBars}
                  analysis={itd.data}
                  gpma={series.data?.series ?? []}
                  gpma2={gpma2.data?.series ?? []}
                  gpma2Status={gpma2.data?.reconciliation_status}
                  gpma2Loading={gpma2.isLoading}
                  gpma2Error={gpma2.isError ? (gpma2.error instanceof Error ? gpma2.error.message : "接口未返回结果") : undefined}
                  focusDate={focusDate}
                  showReversal={false}
                  mode="overview"
                  analysisLoading={itd.isLoading}
                  analysisError={itd.isError ? (itd.error instanceof Error ? itd.error.message : "接口未返回结果") : undefined}
                />
              </section>

              <OverviewIndicators
                gpma={gpma.data}
                volume={volume.data}
                gpmaLoading={gpma.isLoading}
                volumeLoading={volume.isLoading}
                gpmaError={gpma.isError ? (gpma.error instanceof Error ? gpma.error.message : "接口未返回结果") : undefined}
                volumeError={volume.isError ? (volume.error instanceof Error ? volume.error.message : "接口未返回结果") : undefined}
              />

              <section className={`command-action panel panel-decision tone-${actionTone(action?.action)}`}>
                {interpretation.isLoading ? <p>正在计算当前行动建议…</p> : interpretation.isError ? <><span>当前行动建议</span><strong>暂不可用</strong><p>{interpretation.error instanceof Error ? interpretation.error.message : "行动接口未返回结果。"}</p></> : action ? <><div><span>当前行动建议 · 同一快照</span><strong>{action.action_label}</strong><p>{action.position_guidance}</p></div><div className="command-action-score"><b>{action.action_strength}</b><span>/ 100</span><div><i style={{ width: `${action.action_strength}%` }} /></div><small>技术结论 · {action.action}</small></div><div className="command-action-next"><span>现在最需要等待什么</span><p>{action.next_steps[0] ?? "等待下一次确认。"}</p><small>规则提示：不自动下单；卖出仅表示减仓或清仓。</small></div></> : <p>等待行动解释结果…</p>}
              </section>

              <div className="command-bottom-grid">
                <section className="command-evidence panel panel-evidence"><div className="command-panel-heading"><div><span>关键证据</span><h2>当前结论的确认与约束</h2></div><span>{action?.as_of ?? "同一快照"}</span></div>{actionBlocked.length ? <div className="command-blocked"><b>当前限制</b>{actionBlocked.slice(0, 3).map((item) => <p key={item}>{item}</p>)}</div> : <div className="command-evidence-list">{(action?.evidence ?? []).slice(0, 4).map((item, index) => <article key={`${item.source}-${item.label}-${index}`}><StatusBadge tone={directionTone(item.direction)}>{item.source}</StatusBadge><div><b>{item.label}</b><p>{item.detail}</p></div><time>{item.date}</time></article>)}{!action?.evidence.length && <p className="muted">等待可追溯的行动证据。</p>}</div>}</section>
                <section className="command-news panel panel-research"><div className="command-panel-heading"><div><span>新闻中心</span><h2>近期公司新闻</h2></div><button className="text-button" type="button" onClick={() => onOpenNews(symbol)}>打开新闻中心</button></div><div className="command-news-overlay"><StatusBadge tone={action?.news_overlay.effect === "DOWNGRADE" ? "negative" : action?.news_overlay.effect === "CONFIRM" ? "positive" : "neutral"}>{action?.news_overlay.effect ?? "NONE"}</StatusBadge><span>{action?.news_overlay.status === "AVAILABLE" ? `已纳入行动评估 · ${action.news_overlay.applied_points >= 0 ? "+" : ""}${action.news_overlay.applied_points.toFixed(2)} 点` : "新闻不改变当前行动建议"}</span></div>{companyNews.isLoading ? <p className="command-news-empty">正在读取新闻中心缓存…</p> : companyNews.isError ? <p className="command-news-empty">新闻读取失败：{companyNews.error instanceof Error ? companyNews.error.message : "请在新闻中心重试。"}</p> : newsItems.length ? <div className="command-news-list">{newsItems.slice(0, 3).map((item) => <article key={`${item.id}-${item.published_at}`}><div><span>{item.publisher || item.source}</span><time>{item.published_at?.slice(0, 10) ?? "时间未知"}</time></div>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : <b>{item.title}</b>}{item.summary && <p>{item.summary}</p>}</article>)}</div> : <p className="command-news-empty">{companyNews.data?.warning ?? (companyNews.data?.source_status === "DISABLED" ? "新闻功能当前已关闭。" : "未找到该公司的近期合格新闻；可在新闻中心查看来源状态。")}</p>}</section>
              </div>
            </main>
            <aside className="command-sidebar">
              <section className={`command-side-panel command-risk-panel panel panel-risk ${activeAlerts.some((item) => item.severity === "RISK") ? "is-risk" : ""}`}><div className="command-panel-heading"><span>市场风险</span><StatusBadge tone={activeAlerts.some((item) => item.severity === "RISK") ? "negative" : activeAlerts.length ? "warning" : "positive"}>{activeAlerts.some((item) => item.severity === "RISK") ? "RISK" : activeAlerts.length ? "WATCH" : "NORMAL"}</StatusBadge></div><div className="command-risk-summary"><b>{activeAlerts.length ? `${activeAlerts.length} 项活跃预警` : "暂无活跃预警"}</b><small>{riskData?.last_check?.checked_at ? `最近检查 ${riskData.last_check.checked_at}` : "等待风险雷达刷新"}</small></div>{activeAlerts.length ? <div className="command-alert-list">{activeAlerts.slice(0, 5).map((alert) => <article key={alert.id} className={alert.severity === "RISK" ? "is-risk" : "is-watch"}><div><StatusBadge tone={alert.severity === "RISK" ? "negative" : "warning"}>{alert.display_label ?? alert.label}</StatusBadge><time>{alert.date}</time></div><p>{alert.message}</p></article>)}{activeAlerts.length > 5 && <small>另有 {activeAlerts.length - 5} 项活跃预警，请在市场风险雷达查看。</small>}</div> : <p>最近一次检查未发现需要优先处理的预警。</p>}</section>
              <section className={`command-side-panel panel panel-decision tone-${actionTone(action?.action)}`}><div className="command-panel-heading"><span>行动强度</span><StatusBadge tone={actionTone(action?.action)}>{action?.action ?? "等待计算"}</StatusBadge></div><b>{action?.action_strength ?? "—"}<small> / 100</small></b><div className="command-strength-bar"><i style={{ width: `${action?.action_strength ?? 0}%` }} /></div><div className="command-driver-list">{(action?.drivers ?? []).map((driver) => <div key={driver.id}><span>{driver.title}</span><StatusBadge tone={directionTone(driver.status)}>{driver.status}</StatusBadge></div>)}</div></section>
              <section className="command-side-panel panel panel-research"><div className="command-panel-heading"><span>模型与数据</span><StatusBadge tone={volume.data?.data.freshness === "FRESH" ? "positive" : "warning"}>{volume.data?.data.freshness ?? "未知"}</StatusBadge></div><div className="command-model-list"><div><span>GPMAPRO 趋势</span><b>{state?.trend.direction ?? "—"}</b></div><div><span>DELTA 倒转</span><b>{itd.data?.reversal?.state ?? "—"}</b></div><div><span>新闻覆盖层</span><b>{action?.news_overlay.status ?? "等待计算"}</b></div><div><span>验证状态</span><b>{action?.validation.status ?? "—"}</b></div></div></section>
            </aside>
          </div>
          <details className="command-full-decision" onToggle={(event) => setShowFullDecision(event.currentTarget.open)}><summary>查看完整行动解释与审计</summary>{showFullDecision && <SignalInterpretation symbol={symbol} timeframe={timeframe} snapshotId={snapshotId} onFocusDate={setFocusDate} onOpenNews={onOpenNews} />}</details>
        </div>
      )}
    </div>
  );
}

function Backtest() {
  return (
    <div className="terminal-page">
      <PageHeader
        title="回测实验室"
        description="从已导入的 CSV 或不可变 Futu 快照建立可核验数据集；信号与回测将在确认数据后运行。"
      />
      <BacktestDataWorkspace />
    </div>
  );
}

type SystemStatus = {
  status: string;
  started_at: string;
  application: { name: string; app_version: string; environment: string; git_commit: string; git_dirty: boolean | null };
  market_data: { active_provider: string; snapshot_count: number; active: { status?: string; provider?: string; library_version?: string; last_success_at?: string | null } };
  opend: { connected: boolean; connection_check: string; connection_status: string; host: string; port: number; sdk_version: string; last_success_at: string | null; last_snapshot_at: string | null; last_snapshot_id: string | null; snapshot_count: number; error: string | null };
};

function Settings() {
  const status = useQuery<SystemStatus>({ queryKey: ["system-status"], queryFn: () => request("/api/system/status"), refetchInterval: 30_000, retry: false });
  const data = status.data;
  return <div className="terminal-page">
    <PageHeader title="模型设置" description="查看本地研究终端版本、数据连接与运行状态。" />
    {status.isError && <p className="error-banner">无法读取后端运行状态；请确认本地服务已启动。</p>}
    <section className={`panel panel-system p-4 ${data?.market_data.active.status === "UNAVAILABLE" ? "is-blocked" : "is-ready"}`}>
      <PanelHeading title="系统状态" description="只读运行信息；不读取账户或交易数据" meta={data?.started_at ? `启动于 ${data.started_at}` : "等待后端"} />
      <div className="overview-metrics">
        <MetricCard label="后端版本" value={data?.application.app_version ?? "—"} />
        <MetricCard label="Git Commit" value={data?.application.git_commit?.slice(0, 12) ?? "—"} tone={data?.application.git_dirty == null ? "neutral" : data.application.git_dirty ? "negative" : "positive"} />
        <MetricCard label="默认行情源" value={data?.market_data.active_provider?.toUpperCase() ?? "—"} tone="positive" />
        <MetricCard label="行情状态" value={data?.market_data.active.status ?? "—"} />
        <MetricCard label="数据 SDK" value={data?.market_data.active.library_version ?? data?.opend.sdk_version ?? "—"} tone="research" />
        <MetricCard label="本地快照" value={data?.market_data.snapshot_count?.toLocaleString() ?? "—"} />
      </div>
      <p className="panel-footnote">Yahoo 默认无需 API Key；OpenD 仅用于可选的富途公式对账。最近成功保存快照：{data?.market_data.active.last_success_at ?? "尚无记录"}{data?.application.git_dirty ? " · 当前工作树含未提交修改" : ""}</p>
    </section>
  </div>;
}
function Data() {
  const [symbol, setSymbol] = useState("AAPL");
  const [market, setMarket] = useState<Market>("US");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = async () => {
    if (!file) return;
    try {
      const form = new FormData();
      form.append("symbol", resolveMarketCode(symbol, market));
      form.append("file", file);
      setError(null);
      setResult(
        await request("/api/data/import", { method: "POST", body: form }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <div className="terminal-page">
      <PageHeader
        title="数据管理"
        description="继续使用本地 OHLCV CSV 导入；有效字段为 date、open、high、low、close、volume。"
      />
      <section className="panel panel-evidence data-import-workspace p-4">
        <div className="flex gap-2">
          <MarketCodeInput
            market={market}
            value={symbol}
            onMarketChange={setMarket}
            onValueChange={setSymbol}
            className="w-28"
          />
          <input
            className="terminal-input"
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            className="primary-button"
            disabled={!file}
            onClick={() => void upload()}
          >
            导入 CSV
          </button>
        </div>
        {error && <p className="error-banner mt-3">导入失败：{error}</p>}
        {result && (
          <div className="data-import-result mt-4 grid grid-cols-3 gap-3 border-t border-zinc-800 pt-3 text-sm">
            <div>
              <span>数据范围</span>
              <b>
                {result.start_date} → {result.end_date}
              </b>
            </div>
            <div>
              <span>总 K 线 / 新增</span>
              <b>
                {result.rows_imported} / {result.new_bars} bars
              </b>
            </div>
            <div>
              <span>最新 K 线 / 状态</span>
              <b>
                {result.latest_bar_date} · {result.freshness}
              </b>
            </div>
            <p className="col-span-3 text-xs text-zinc-400">
              {result.warning ??
                (result.import_status === "UNCHANGED"
                  ? "导入成功，但最新交易日期没有变化。"
                  : "数据已更新。")}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
function FutuSnapshotData() {
  const [code, setCode] = useState("VXN");
  const [market, setMarket] = useState<Market>("US");
  const [timeframe, setTimeframe] = useState("1d");
  const [autype, setAutype] = useState("QFQ");
  const [start, setStart] = useState("2018-01-01");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const fetchSnapshot = async () => {
    setError(null);
    try {
      setResult(
        await request("/api/data/market/snapshots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code: resolveMarketCode(code, market),
            timeframe,
            adjustment: autype === "NONE" ? "raw" : "adjusted",
            start,
          }),
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <section className="panel panel-research mt-4 p-4">
      <div className="panel-title">市场行情快照</div>
      <p className="mt-1 text-xs text-zinc-500">
        默认使用 Yahoo Finance 拉取历史 K 线；每次生成不可覆盖快照，不读取账户或交易数据。
      </p>
      <div className="data-toolbar mt-3 flex gap-2">
        <MarketCodeInput
          market={market}
          value={code}
          onMarketChange={setMarket}
          onValueChange={setCode}
          className="w-32"
        />
        <select
          className="terminal-input"
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
        >
          <option value="1d">日线</option>
          <option value="1w">周线</option>
          <option value="1mo">月线</option>
        </select>
        <select
          className="terminal-input"
          value={autype}
          onChange={(e) => setAutype(e.target.value)}
        >
          <option value="QFQ">前复权 QFQ</option>
          <option value="NONE">不复权</option>
        </select>
        <input
          className="terminal-input"
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
        <button className="primary-button" onClick={() => void fetchSnapshot()}>
          拉取并保存快照
        </button>
      </div>
      {result && (
        <p className="mt-3 text-xs text-emerald-300">
          已保存 {result.snapshot_id} · {result.bar_count} bars · SHA256{" "}
          {result.data_sha256?.slice(0, 12)}
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-rose-300">行情拉取失败：{error}</p>
      )}
    </section>
  );
}
export default function App() {
  const [page, setPage] = useState("overview");
  const [newsContext, setNewsContext] = useState({ code: "US.AAPL", openDetails: false, key: 0 });
  const [overviewContext, setOverviewContext] = useState({ code: "US.VXN", key: 0 });
  const [navigationOpen, setNavigationOpen] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 768,
  );
  const [checking, setChecking] = useState(false);
  const [alertError, setAlertError] = useState<string | null>(null);
  const initialAlertRefreshStarted = useRef(false);
  const marketAlerts = useQuery<MarketAlertSnapshot>({
    queryKey: ["market-volatility-alerts"],
    queryFn: () => request("/api/market-volatility-alerts"),
    retry: false,
  });
  const { refetch: refetchMarketAlerts } = marketAlerts;
  const checkAlerts = useCallback(async () => {
    setChecking(true);
    setAlertError(null);
    try {
      const result = await request("/api/market-volatility-alerts/check", {
        method: "POST",
      });
      const created = result.created_alerts as Array<{
        severity: string;
        label: string;
        message: string;
      }>;
      if (
        created.length &&
        "Notification" in window &&
        Notification.permission === "granted"
      )
        new Notification(
          created.some((item) => item.severity === "RISK")
            ? "DELTA：市场高风险预警"
            : "DELTA：市场波动预警",
          {
            body: created
              .map((item) => `${item.label} ${item.message}`)
              .join("；"),
          },
        );
      await refetchMarketAlerts();
    } catch (error) {
      setAlertError(error instanceof Error ? error.message : String(error));
    } finally {
      setChecking(false);
    }
  }, [refetchMarketAlerts]);
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default")
      void Notification.requestPermission();
    if (initialAlertRefreshStarted.current) return;
    initialAlertRefreshStarted.current = true;
    void checkAlerts();
  }, [checkAlerts]);
  const openNews = useCallback((code: string) => {
    setNewsContext(previous => ({ code, openDetails: true, key: previous.key + 1 }));
    setPage("news");
  }, []);
  const openOverview = useCallback((code: string) => {
    setOverviewContext(previous => ({ code: code.toUpperCase(), key: previous.key + 1 }));
    setPage("overview");
  }, []);
  const nav = useMemo(
    () => [
      { id: "overview", label: "总览", Icon: Gauge },
      { id: "alerts", label: "市场风险雷达", Icon: BellRing },
      { id: "backtest", label: "回测实验室", Icon: BarChart3 },
      { id: "data", label: "数据管理", Icon: Database },
      { id: "news", label: "新闻中心", Icon: Newspaper },
      { id: "options", label: "期权雷达", Icon: Radar },
      { id: "stock-pool", label: "股票池", Icon: Layers3 },
      { id: "settings", label: "模型设置", Icon: Settings2 },
    ],
    [],
  );
  const pages: Record<string, ReactNode> = {
    overview: <Overview onOpenNews={openNews} riskData={marketAlerts.data} initialCode={overviewContext.code} contextKey={overviewContext.key} />,
    alerts: (
      <MarketVolatilityAlerts
        data={marketAlerts.data}
        onCheck={() => void checkAlerts()}
        checking={checking}
        refresh={() => refetchMarketAlerts()}
      />
    ),
    backtest: <Backtest />,
    data: (
      <>
        <Data />
        <FutuSnapshotData />
        <ResearchDataset />
      </>
    ),
    news: <NewsCenter initialCode={newsContext.code} initialDetailsOpen={newsContext.openDetails} contextKey={newsContext.key} onOpenOptions={() => setPage("options")} onOpenOverview={openOverview} />,
    options: <OptionsRadar />,
    "stock-pool": <StockPool />,
    settings: <Settings />,
  };
  const activePage =
    nav.find((item) => item.id === page)?.label ?? "DELTA 时空研究终端";
  return (
    <Theme theme="g100">
      <main
        className={`workspace-shell ${navigationOpen ? "nav-open" : "nav-collapsed"}`}
      >
        <aside className="workspace-nav" aria-label="主导航">
          <div className="workspace-brand">
            <span className="brand-mark">Δ</span>
            <div>
              <strong>DELTA</strong>
              <small>TIME + GPMAPRO</small>
            </div>
          </div>
          <nav>
            {nav.map(({ id, label, Icon }) => (
              <button
                key={id}
                onClick={() => {
                  if (id === "news") setNewsContext(previous => ({ ...previous, openDetails: false, key: previous.key + 1 }));
                  setPage(id);
                  if (window.innerWidth < 768) setNavigationOpen(false);
                }}
                className={`nav-button ${page === id ? "active" : ""}`}
                aria-label={label}
                aria-current={page === id ? "page" : undefined}
              >
                <Icon size={17} strokeWidth={1.7} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
          <div className="workspace-nav-footer">
            <Tag type="cyan" size="sm">
              RESEARCH MODE
            </Tag>
          </div>
        </aside>
        <section className="workspace-main">
          <header className="workspace-header">
            <div className="workspace-header-start">
              <Button
                kind="ghost"
                size="sm"
                hasIconOnly
                renderIcon={navigationOpen ? ChevronLeft : Menu}
                iconDescription={navigationOpen ? "收起导航" : "展开导航"}
                onClick={() => setNavigationOpen((value) => !value)}
              />
              <div>
                <p>量化研究工作台</p>
                <strong>{activePage}</strong>
              </div>
            </div>
            <Tag
              type={
                (
                  marketAlerts.data?.active_alerts ??
                  marketAlerts.data?.alerts ??
                  []
                ).some((item) => !item.read && item.severity === "RISK")
                  ? "red"
                  : "cyan"
              }
              size="sm"
            >
              {checking ? "正在检查风险" : "行情与研究分离"}
            </Tag>
          </header>
          <MarketAlertBanner
            data={marketAlerts.data}
            onCheck={() => void checkAlerts()}
            checking={checking}
            error={alertError}
          />
          <div className="workspace-content">{pages[page]}</div>
        </section>
      </main>
    </Theme>
  );
}
