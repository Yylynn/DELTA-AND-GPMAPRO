import {
  useCallback,
  useEffect,
  useMemo,
  useState,
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
  const highest = unread.some((item) => item.severity === "RISK")
    ? "RISK"
    : unread.length
      ? "WATCH"
      : "NORMAL";
  const action = (
    <Button kind="ghost" size="sm" onClick={onCheck} disabled={checking}>
      {checking ? <InlineLoading description="刷新中" /> : "立即刷新"}
    </Button>
  );
  if (!unread.length)
    return (
      <div className={`market-alert-banner ${error ? "watch" : "normal"}`}>
        <BellRing size={16} />
        <span>
          {error
            ? `市场风险雷达刷新失败：${error}`
            : "市场风险雷达：暂无未读预警"}
        </span>
        {action}
      </div>
    );
  return (
    <div className={`market-alert-banner ${highest.toLowerCase()}`}>
      <BellRing size={16} />
      <div>
        <b>{highest === "RISK" ? "市场高风险预警" : "市场波动预警"}</b>
        <span>
          {unread.map((item) => `${item.label}：${item.message}`).join("；")}
        </span>
      </div>
      {action}
    </div>
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
      <section className="panel p-4">
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
      <section className="panel mt-4 overflow-hidden">
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
      <section className="panel mt-4 overflow-hidden">
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
      <section className="panel mt-4 overflow-hidden">
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
      <section className="panel mt-4 overflow-hidden">
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

function Overview({ onOpenNews }: { onOpenNews: (symbol: string) => void }) {
  const [symbol, setSymbol] = useState("US.VXN");
  const [draft, setDraft] = useState("VXN");
  const [market, setMarket] = useState<Market>("US");
  const [timeframe, setTimeframe] = useState("1d");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<
    string | undefined
  >();
  const [focusDate, setFocusDate] = useState<string | undefined>();
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<{
    snapshot_id: string;
    code: string;
    bar_count: number;
    end_date?: string;
  } | null>(null);
  const snapshots = useQuery<{ snapshots: Snapshot[] }>({
    queryKey: ["futu-snapshots"],
    queryFn: () => request("/api/data/futu/snapshots"),
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
  const refresh = async () => {
    let code: string;
    try {
      code = resolveMarketCode(draft, market);
    } catch (error) {
      setFetchError(error instanceof Error ? error.message : String(error));
      return;
    }
    setFetching(true);
    setFetchError(null);
    try {
      const created = await request("/api/data/futu/snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          timeframe: "1d",
          autype: "QFQ",
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
  const bars = useQuery<{
    bars: Array<Omit<ChartBar, "time"> & { date: string }>;
  }>({
    queryKey: ["bars", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(
        `/api/data/futu/snapshots/${snapshotId}/ohlcv?timeframe=${timeframe}`,
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
  const gpma = useQuery<{
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
  }>({
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
  useQuery<{ series: GpmaSeries[] }>({
    queryKey: ["gpma2-series", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(
        `/api/gpma2/${symbol}/series?timeframe=${timeframe}${snapshotQuery}`,
      ),
    enabled: Boolean(snapshotId && timeframe === "1d"),
    retry: false,
  });
  const volume = useQuery<{
    as_of: string;
    latest_volume: number;
    volume_ma20: number;
    relative_volume: number;
    volume_level: string;
    volume_trend: string;
    volume_anomaly: string;
    price_volume_context: string;
    data: { freshness: string; latest_bar_date: string };
  }>({
    queryKey: ["volume", symbol, timeframe, snapshotId],
    queryFn: () =>
      request(`/api/volume/${symbol}?timeframe=${timeframe}${snapshotQuery}`),
    enabled: Boolean(snapshotId),
    retry: false,
  });
  const chartBars = (bars.data?.bars ?? []).map((bar) => ({
    ...bar,
    time: bar.date,
  }));
  const state = gpma.data;
  return (
    <div className="terminal-page">
      <PageHeader
        title="总览"
        description="输入富途代码并按回车，即时创建 OpenD 行情快照；不连接交易账户或下单。"
        actions={<form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void refresh();
          }}
        >
          <span className="text-xs text-zinc-400">
            {fetching
              ? "OpenD 拉取中…"
              : `Latest Bar ${volume.data?.data.latest_bar_date ?? "—"}`}
          </span>
          <MarketCodeInput
            market={market}
            value={draft}
            onMarketChange={setMarket}
            onValueChange={setDraft}
            className="w-32"
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
        </form>}
      />
      {fetchError && (
        <p className="error-banner mb-3">OpenD 拉取失败：{fetchError}</p>
      )}
      {lastFetch && (
        <p className="mb-3 text-xs text-emerald-300">
          已切换至 {lastFetch.code} · {lastFetch.bar_count} bars · 快照{" "}
          {lastFetch.snapshot_id}
        </p>
      )}
      <SkillDeltaChart
        bars={chartBars}
        analysis={itd.data}
        focusDate={focusDate}
      />
      <SignalInterpretation
        symbol={symbol}
        timeframe={timeframe}
        snapshotId={snapshotId}
        onFocusDate={setFocusDate}
        onOpenNews={onOpenNews}
      />
      <div className="overview-status-grid">
        <section className="panel p-4">
          <PanelHeading
            title="GPMAPRO 当前状态"
            description="趋势、过滤器与交易层级的同一快照"
            meta={`as of ${state?.as_of ?? "—"}`}
          />
          <div className="overview-metrics">
            <MetricCard label="趋势" value={`${state?.trend.direction ?? "—"} · ${state?.trend.strength ?? "—"}`} tone={state?.trend.direction === "BULLISH" ? "positive" : state?.trend.direction === "BEARISH" ? "negative" : "neutral"} />
            <MetricCard label="成交量" value={`${state?.volume.ratio?.toFixed(2) ?? "—"}×`} />
            <MetricCard label="过滤器" value={`Gap ${bool(state?.filters.gap_ok ?? false)} · Range ${bool(state?.filters.range_ok ?? false)}`} />
            <MetricCard label="信号" value={Object.entries(state?.signals ?? {}).filter(([, active]) => active).map(([key]) => key.toUpperCase()).join(" · ") || "—"} />
          </div>
          <div className="signal-levels">
            {Object.entries(state?.signals ?? {}).map(([key, active]) => (
              <StatusBadge key={key} tone={active ? (key.startsWith("b") ? "positive" : "negative") : "neutral"}>
                {key.toUpperCase()} {bool(active)}
              </StatusBadge>
            ))}
          </div>
        </section>
        <section className="panel p-4">
          <PanelHeading title="成交量快照" description="基于所选日/周/月已完成 K 线计算；不是盘中实时成交量" meta="OpenD 同一不可变快照" />
          <div className="overview-metrics overview-volume-metrics">
            <MetricCard label="成交量状态" value={volume.data?.volume_level ?? "—"} />
            <MetricCard label="RVOL" value={`${volume.data?.relative_volume?.toFixed(2) ?? "—"}×`} />
            <MetricCard label="短期趋势" value={volume.data?.volume_trend ?? "—"} />
            <MetricCard label="异常" value={volume.data?.volume_anomaly ?? "—"} tone={volume.data?.volume_anomaly && volume.data.volume_anomaly !== "NONE" ? "negative" : "positive"} />
            <MetricCard label="最新成交量" value={volume.data?.latest_volume?.toLocaleString() ?? "—"} />
            <MetricCard label="20周期均量" value={volume.data?.volume_ma20?.toLocaleString() ?? "—"} />
          </div>
          <p className="panel-footnote">
            {volume.data?.price_volume_context ?? "—"}
          </p>
        </section>
      </div>
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
  opend: { connected: boolean; connection_check: string; connection_status: string; host: string; port: number; sdk_version: string; last_success_at: string | null; last_snapshot_at: string | null; last_snapshot_id: string | null; snapshot_count: number; error: string | null };
};

function Settings() {
  const status = useQuery<SystemStatus>({ queryKey: ["system-status"], queryFn: () => request("/api/system/status"), refetchInterval: 30_000, retry: false });
  const data = status.data;
  return <div className="terminal-page">
    <PageHeader title="模型设置" description="查看本地研究终端版本、数据连接与运行状态。" />
    {status.isError && <p className="error-banner">无法读取后端运行状态；请确认本地服务已启动。</p>}
    <section className="panel p-4">
      <PanelHeading title="系统状态" description="只读运行信息；不读取账户或交易数据" meta={data?.started_at ? `启动于 ${data.started_at}` : "等待后端"} />
      <div className="overview-metrics">
        <MetricCard label="后端版本" value={data?.application.app_version ?? "—"} />
        <MetricCard label="Git Commit" value={data?.application.git_commit?.slice(0, 12) ?? "—"} tone={data?.application.git_dirty == null ? "neutral" : data.application.git_dirty ? "negative" : "positive"} />
        <MetricCard label="OpenD 端口" value={data?.opend.connected ? "可达" : "不可达"} tone={data?.opend.connected ? "positive" : "negative"} />
        <MetricCard label="OpenD 地址" value={data ? `${data.opend.host}:${data.opend.port}` : "—"} />
        <MetricCard label="SDK" value={data?.opend.sdk_version ?? "—"} />
        <MetricCard label="本地快照" value={data?.opend.snapshot_count?.toLocaleString() ?? "—"} />
      </div>
      <p className="panel-footnote">连接检查：TCP 端点探测，不代表行情权限或 SDK 请求成功。最近成功保存快照：{data?.opend.last_snapshot_at ?? "尚无记录"}{data?.application.git_dirty ? " · 当前工作树含未提交修改" : ""}</p>
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
      <section className="panel p-4">
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
          <div className="mt-4 grid grid-cols-3 gap-3 border-t border-zinc-800 pt-3 text-sm">
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
        await request("/api/data/futu/snapshots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code: resolveMarketCode(code, market),
            timeframe,
            autype,
            start,
          }),
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <section className="panel mt-4 p-4">
      <div className="panel-title">富途 OpenD 行情快照</div>
      <p className="mt-1 text-xs text-zinc-500">
        仅拉取授权行情与历史 K 线；每次生成不可覆盖快照，不读取账户或交易数据。
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
          <option value="HFQ">后复权 HFQ</option>
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
        <p className="mt-3 text-xs text-rose-300">OpenD 拉取失败：{error}</p>
      )}
    </section>
  );
}
export default function App() {
  const [page, setPage] = useState("overview");
  const [newsContext, setNewsContext] = useState({ code: "US.AAPL", openDetails: false, key: 0 });
  const [navigationOpen, setNavigationOpen] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 768,
  );
  const [checking, setChecking] = useState(false);
  const [alertError, setAlertError] = useState<string | null>(null);
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
    void checkAlerts();
  }, []);
  useEffect(() => {
    if (page === "overview") void checkAlerts();
  }, [page, checkAlerts]);
  const openNews = useCallback((code: string) => {
    setNewsContext(previous => ({ code, openDetails: true, key: previous.key + 1 }));
    setPage("news");
  }, []);
  const nav = useMemo(
    () => [
      { id: "overview", label: "总览", Icon: Gauge },
      { id: "alerts", label: "市场风险雷达", Icon: BellRing },
      { id: "backtest", label: "回测实验室", Icon: BarChart3 },
      { id: "data", label: "数据管理", Icon: Database },
      { id: "news", label: "新闻中心", Icon: Newspaper },
      { id: "settings", label: "模型设置", Icon: Settings2 },
    ],
    [],
  );
  const pages: Record<string, ReactNode> = {
    overview: <Overview onOpenNews={openNews} />,
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
    news: <NewsCenter initialCode={newsContext.code} initialDetailsOpen={newsContext.openDetails} contextKey={newsContext.key} />,
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
