import { lazy, Suspense, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, CandlestickChart, Eye, EyeOff } from "lucide-react";
import {
  BacktestSignalChart,
  type PreviewBar,
  type SignalEvent,
} from "@/components/BacktestSignalChart";
import { backtestSignalLabel } from "@/components/backtestSignalLabels";
import type { BacktestResult } from "@/components/backtestResultTypes";
import { PanelHeading } from "@/components/ui/workspace";

const BacktestRuleLab = lazy(() => import("@/components/BacktestRuleLab").then(
  (module) => ({ default: module.BacktestRuleLab }),
));

type LoadedDataset = {
  dataset_id: string;
  symbol: string;
  bar_count: number;
  data_sha256: string | null;
  start_date: string | null;
  end_date: string | null;
};

type LoadedSelection = {
  selection_id: string;
  datasets: LoadedDataset[];
};

type SignalCatalogItem = {
  code: string;
  family: "B" | "S" | "DIVERGENCE" | "DELTA";
  direction: "BUY" | "SELL";
  full_count: number;
  display_count: number;
};

type SignalPreview = {
  dataset: LoadedDataset;
  range: {
    years: number;
    start: string;
    end: string;
    display_bar_count: number;
    full_bar_count: number;
  };
  bars: PreviewBar[];
  signal_catalog: SignalCatalogItem[];
  events: SignalEvent[];
  delta: {
    status: string | null;
    history_confidence: string | null;
    confirmed_point_count: number;
  };
};

const requestPreview = async (datasetId: string, years: number) => {
  const response = await fetch("/api/backtest/datasets/signal-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, years }),
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const payload = JSON.parse(text) as { detail?: string };
      message = payload.detail ?? text;
    } catch {
      // Keep the plain response body when the backend did not return JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<SignalPreview>;
};

export function BacktestSignalExplorer({
  loaded,
  onBacktestComplete,
}: {
  loaded: LoadedSelection;
  onBacktestComplete: (result: BacktestResult) => void;
}) {
  const [preferredDatasetId, setPreferredDatasetId] = useState(
    loaded.datasets[0]?.dataset_id ?? "",
  );
  const [years, setYears] = useState(2);
  const [hiddenSignals, setHiddenSignals] = useState<Set<string>>(() => new Set());
  const activeDatasetId = loaded.datasets.some(
    (dataset) => dataset.dataset_id === preferredDatasetId,
  )
    ? preferredDatasetId
    : loaded.datasets[0]?.dataset_id ?? "";
  const preview = useQuery<SignalPreview>({
    queryKey: ["backtest-signal-preview", loaded.selection_id, activeDatasetId, years],
    queryFn: () => requestPreview(activeDatasetId, years),
    enabled: Boolean(activeDatasetId),
    retry: false,
  });
  const visibleSignals = useMemo(
    () => new Set((preview.data?.signal_catalog ?? [])
      .map((signal) => signal.code)
      .filter((code) => !hiddenSignals.has(code))),
    [hiddenSignals, preview.data?.signal_catalog],
  );
  const groups = useMemo(() => ({
    B: (preview.data?.signal_catalog ?? []).filter((signal) => signal.family === "B"),
    S: (preview.data?.signal_catalog ?? []).filter((signal) => signal.family === "S"),
    DIVERGENCE: (preview.data?.signal_catalog ?? []).filter((signal) => signal.family === "DIVERGENCE"),
    DELTA: (preview.data?.signal_catalog ?? []).filter((signal) => signal.family === "DELTA"),
  }), [preview.data?.signal_catalog]);

  const toggleSignal = (code: string) => {
    setHiddenSignals((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <section className="panel backtest-workspace-panel">
      <PanelHeading
        title="④ K 线与信号预览"
        description="先用完整历史计算信号，再截取最近区间显示；图例只控制可见性，不会改变已加载数据。"
        meta="收盘确认 · 下一交易日可交易"
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-xs text-zinc-400">
          当前预览资产
          <select
            className="terminal-input mt-1 min-w-56"
            value={activeDatasetId}
            onChange={(event) => setPreferredDatasetId(event.target.value)}
          >
            {loaded.datasets.map((dataset) => (
              <option value={dataset.dataset_id} key={dataset.dataset_id}>
                {dataset.symbol} · {dataset.bar_count} bars
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-2" aria-label="K 线预览范围">
          {[1, 2].map((value) => (
            <button
              className={years === value ? "primary-button" : "secondary-button"}
              key={value}
              onClick={() => setYears(value)}
              aria-pressed={years === value}
            >
              最近 {value} 年
            </button>
          ))}
        </div>
        <button
          className="secondary-button inline-flex items-center gap-2"
          onClick={() => void preview.refetch()}
          disabled={preview.isFetching}
        >
          <Activity size={14} /> {preview.isFetching ? "计算中…" : "重新计算信号"}
        </button>
      </div>

      {preview.isLoading && (
        <div className="flex min-h-72 items-center justify-center border border-zinc-800 text-sm text-zinc-500">
          正在读取完整历史并计算全部信号…
        </div>
      )}
      {preview.isError && (
        <p className="error-banner">
          信号预览不可用：{preview.error instanceof Error ? preview.error.message : "未知错误"}
        </p>
      )}
      {preview.data && (
        <>
          <div className="mb-4 grid grid-cols-5 gap-3 text-sm">
            <div className="border border-zinc-800 p-3">
              <span>显示区间</span>
              <b>{preview.data.range.start} 至 {preview.data.range.end}</b>
            </div>
            <div className="border border-zinc-800 p-3">
              <span>显示 K 线</span>
              <b>{preview.data.range.display_bar_count.toLocaleString()}</b>
            </div>
            <div className="border border-zinc-800 p-3">
              <span>完整历史</span>
              <b>{preview.data.range.full_bar_count.toLocaleString()}</b>
            </div>
            <div className="border border-zinc-800 p-3">
              <span>DELTA 状态</span>
              <b>{preview.data.delta.status ?? "—"}</b>
            </div>
            <div className="border border-zinc-800 p-3">
              <span>已确认 DELTA</span>
              <b>{preview.data.delta.confirmed_point_count}</b>
            </div>
          </div>
          <BacktestSignalChart
            key={`${activeDatasetId}:${years}`}
            bars={preview.data.bars}
            events={preview.data.events}
            visibleSignals={visibleSignals}
          />
          <div className="backtest-signal-legend border border-zinc-800 p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <CandlestickChart size={16} className="text-cyan-300" />
                <b className="text-sm">图上显示的信号</b>
                <span className="text-xs text-zinc-500">数字为当前显示区间内的出现次数</span>
              </div>
              <div className="flex gap-2">
                <button className="secondary-button inline-flex items-center gap-1" onClick={() => setHiddenSignals(new Set())}>
                  <Eye size={14} /> 全部显示
                </button>
                <button
                  className="secondary-button inline-flex items-center gap-1"
                  onClick={() => setHiddenSignals(new Set(preview.data.signal_catalog.map((signal) => signal.code)))}
                >
                  <EyeOff size={14} /> 全部隐藏
                </button>
              </div>
            </div>
            {(["B", "S", "DIVERGENCE", "DELTA"] as const).map((family) => (
              <div className="mt-3 grid grid-cols-[72px_1fr] items-start gap-3" key={family}>
                <span className="pt-2 text-xs text-zinc-500">
                  {family === "B" ? "买入信号" : family === "S" ? "卖出信号" : family === "DIVERGENCE" ? "背离信号" : "DELTA"}
                </span>
                <div className="flex flex-wrap gap-2">
                  {groups[family].map((signal) => {
                    const visible = visibleSignals.has(signal.code);
                    return (
                      <button
                        className={visible ? "primary-button" : "secondary-button"}
                        key={signal.code}
                        onClick={() => toggleSignal(signal.code)}
                        aria-pressed={visible}
                        title={`完整历史 ${signal.full_count} 次`}
                      >
                        {backtestSignalLabel(signal.code)} · {signal.display_count}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <p className="panel-footnote">
            B/S 与背离图标位于信号确认的收盘日，下一交易日才可交易；DELTA LOW/HIGH 标记位于确认后的可交易日。图例显示或隐藏信号不会触发重新计算。
          </p>
          <Suspense fallback={<p className="mt-6 border-t border-zinc-800 pt-6 text-sm text-zinc-500">正在加载回测规则界面…</p>}>
            <BacktestRuleLab
              key={activeDatasetId}
              dataset={{
                ...preview.data.dataset,
                start_date: preview.data.dataset.start_date ?? preview.data.range.start,
                end_date: preview.data.dataset.end_date ?? preview.data.range.end,
              }}
              signalCatalog={preview.data.signal_catalog}
              onComplete={onBacktestComplete}
            />
          </Suspense>
        </>
      )}
    </section>
  );
}
