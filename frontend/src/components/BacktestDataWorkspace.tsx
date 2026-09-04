import { lazy, Suspense, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Cloud,
  Database,
  FileSpreadsheet,
  LockKeyhole,
  RefreshCw,
} from "lucide-react";
import { PanelHeading } from "@/components/ui/workspace";
import { BacktestSignalExplorer } from "@/components/BacktestSignalExplorer";
import type { BacktestResult } from "@/components/backtestResultTypes";

const BacktestResultWorkspace = lazy(() => import("@/components/BacktestResultWorkspace").then(
  (module) => ({ default: module.BacktestResultWorkspace }),
));

type DatasetSource = "local_csv" | "futu_snapshot";

type ResearchDataset = {
  dataset_id: string;
  source: DatasetSource;
  symbol: string;
  timeframe: string;
  bar_count: number;
  start_date: string | null;
  end_date: string | null;
  latest_bar_date: string | null;
  freshness: string;
  days_since_latest_bar: number | null;
  autype: string | null;
  adjustment: string;
  research_eligibility: string;
  quality: string;
  warnings: string[];
  snapshot_id: string | null;
  data_sha256: string | null;
  fetched_at: string | null;
  selectable: boolean;
  verification?: string;
};

type DatasetCatalog = {
  datasets: ResearchDataset[];
  counts: Record<DatasetSource, number>;
};

type LoadedSelection = {
  selection_id: string;
  loaded_at: string;
  source: DatasetSource;
  dataset_count: number;
  datasets: ResearchDataset[];
  common_date_range: { start: string | null; end: string | null };
  research_eligibility: string;
  warnings: string[];
};

const request = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, options);
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
  return response.json() as Promise<T>;
};

const sourceNames: Record<DatasetSource, string> = {
  local_csv: "本地 CSV",
  futu_snapshot: "Futu 快照",
};

const freshnessNames: Record<string, string> = {
  CURRENT: "当前",
  STALE: "稍旧",
  VERY_STALE: "较旧",
  UNKNOWN: "未知",
};

const eligibilityNames: Record<string, string> = {
  ELIGIBLE: "合格",
  LIMITED: "有限",
  INELIGIBLE: "不足",
};

const sameIds = (left: string[], right: string[]) =>
  [...left].sort().join("|") === [...right].sort().join("|");

function Eligibility({ value }: { value: string }) {
  const tone =
    value === "ELIGIBLE"
      ? "border-emerald-800 text-emerald-300"
      : value === "LIMITED"
        ? "border-amber-800 text-amber-300"
        : "border-rose-800 text-rose-300";
  return (
    <span className={`inline-flex border px-2 py-1 text-xs ${tone}`}>
      {eligibilityNames[value] ?? value}
    </span>
  );
}

export function BacktestDataWorkspace() {
  const [source, setSource] = useState<DatasetSource>("local_csv");
  const [draftIds, setDraftIds] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<LoadedSelection | null>(null);
  const [lastResult, setLastResult] = useState<BacktestResult | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const catalog = useQuery<DatasetCatalog>({
    queryKey: ["backtest-dataset-catalog"],
    queryFn: () => request("/api/backtest/datasets"),
    retry: false,
  });
  const rows = useMemo(
    () =>
      (catalog.data?.datasets ?? []).filter(
        (dataset) => dataset.source === source,
      ),
    [catalog.data?.datasets, source],
  );
  const selectableIds = rows
    .filter((dataset) => dataset.selectable)
    .map((dataset) => dataset.dataset_id);
  const loadedIds = loaded?.datasets.map((dataset) => dataset.dataset_id) ?? [];
  const hasUnappliedChanges = Boolean(
    loaded && !sameIds(draftIds, loadedIds),
  );

  const changeSource = (next: DatasetSource) => {
    setSource(next);
    setDraftIds([]);
    setLoadError(null);
  };

  const toggle = (datasetId: string) => {
    setDraftIds((current) =>
      current.includes(datasetId)
        ? current.filter((item) => item !== datasetId)
        : [...current, datasetId],
    );
    setLoadError(null);
  };

  const loadSelection = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await request<LoadedSelection>(
        "/api/backtest/datasets/load",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dataset_ids: draftIds }),
        },
      );
      setLoaded(result);
      setLastResult(null);
      setShowResult(false);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  };

  if (showResult && lastResult) {
    return (
      <Suspense fallback={<section className="panel p-6 text-sm text-zinc-500">正在打开回测结果…</section>}>
        <BacktestResultWorkspace
          result={lastResult}
          onBack={() => setShowResult(false)}
        />
      </Suspense>
    );
  }

  return (
    <div className="backtest-workspace-stack grid">
      <section className="panel backtest-workspace-panel">
        <PanelHeading
          title="① 数据来源"
          description="选择数据目录；切换来源只改变待选列表，不会静默替换已经加载的数据集。"
          meta="第一版仅支持日线"
        />
        <div className="grid grid-cols-2 gap-3">
          <button
            className={source === "local_csv" ? "primary-button" : "secondary-button"}
            onClick={() => changeSource("local_csv")}
          >
            <span className="inline-flex items-center gap-2">
              <FileSpreadsheet size={16} /> 本地 CSV · {catalog.data?.counts.local_csv ?? 0}
            </span>
          </button>
          <button
            className={source === "futu_snapshot" ? "primary-button" : "secondary-button"}
            onClick={() => changeSource("futu_snapshot")}
          >
            <span className="inline-flex items-center gap-2">
              <Cloud size={16} /> Futu 快照 · {catalog.data?.counts.futu_snapshot ?? 0}
            </span>
          </button>
        </div>
        <p className="mt-3 text-xs text-zinc-500">
          CSV 的复权方式无法从 OHLCV 自动判断；Futu 快照沿用保存时记录的复权方式和内容指纹。
        </p>
      </section>

      <section className="panel backtest-workspace-panel overflow-hidden">
        <div>
          <PanelHeading
            title="② 选择数据"
            description={`从已有的${sourceNames[source]}目录勾选标的，不需要手工输入代码。`}
            meta={`${draftIds.length} 个待加载`}
          />
          <div className="mb-4 flex flex-wrap gap-2">
            <button
              className="secondary-button inline-flex items-center gap-2"
              onClick={() => void catalog.refetch()}
              disabled={catalog.isFetching}
            >
              <RefreshCw size={14} />
              {catalog.isFetching ? "刷新中…" : "刷新目录"}
            </button>
            <button
              className="secondary-button"
              onClick={() => setDraftIds(selectableIds)}
              disabled={!selectableIds.length}
            >
              全选当前来源
            </button>
            <button
              className="secondary-button"
              onClick={() => setDraftIds([])}
              disabled={!draftIds.length}
            >
              清空选择
            </button>
          </div>
        </div>

        {catalog.isError && (
          <p className="error-banner">
            无法读取数据目录：请确认本地后端已经启动。
          </p>
        )}
        {!catalog.isError && !catalog.isLoading && !rows.length && (
          <div className="text-sm text-zinc-500">
            当前没有{sourceNames[source]}。请先在“数据管理”中上传 CSV 或创建 Futu 快照。
          </div>
        )}
        {rows.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>选择</th>
                <th>标的 / 数据标识</th>
                <th>K 线</th>
                <th>日期范围</th>
                <th>新鲜度</th>
                <th>复权</th>
                <th>质量</th>
                <th>资格</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((dataset) => (
                <tr key={dataset.dataset_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={draftIds.includes(dataset.dataset_id)}
                      disabled={!dataset.selectable}
                      onChange={() => toggle(dataset.dataset_id)}
                      aria-label={`选择 ${dataset.symbol}`}
                    />
                  </td>
                  <td>
                    <b>{dataset.symbol}</b>
                    <span className="mt-1 block font-mono text-[11px] text-zinc-500">
                      {dataset.snapshot_id
                        ? dataset.snapshot_id.slice(0, 24)
                        : dataset.dataset_id}
                    </span>
                  </td>
                  <td>{dataset.bar_count.toLocaleString()} · 日线</td>
                  <td>
                    {dataset.start_date ?? "—"}
                    <span className="block text-xs text-zinc-500">
                      至 {dataset.end_date ?? "—"}
                    </span>
                  </td>
                  <td>
                    {freshnessNames[dataset.freshness] ?? dataset.freshness}
                    {dataset.days_since_latest_bar != null && (
                      <span className="block text-xs text-zinc-500">
                        距最后 K 线 {dataset.days_since_latest_bar} 天
                      </span>
                    )}
                  </td>
                  <td>{dataset.adjustment === "UNRECORDED" ? "未记录" : dataset.adjustment}</td>
                  <td>
                    {dataset.quality}
                    {dataset.warnings.length > 0 && (
                      <span className="block text-xs text-amber-300">
                        {dataset.warnings.join("；")}
                      </span>
                    )}
                  </td>
                  <td><Eligibility value={dataset.research_eligibility} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel backtest-workspace-panel">
        <PanelHeading
          title="③ 检查并加载数据集"
          description="只有点击加载后，所选目录项才成为后续信号计算和回测使用的确认数据集。"
          meta={hasUnappliedChanges ? "有未应用的选择" : loaded ? "已确认" : "等待加载"}
        />
        {loadError && <p className="error-banner">加载失败：{loadError}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button
            className="primary-button inline-flex items-center gap-2"
            disabled={!draftIds.length || loading}
            onClick={() => void loadSelection()}
          >
            <Database size={15} />
            {loading ? "正在校验…" : `加载 ${draftIds.length || ""} 个数据集`}
          </button>
          <span className="text-xs text-zinc-500">
            加载时会重新校验文件、快照完整性和日线资格。
          </span>
        </div>

        {loaded && (
          <div className="mt-4 border border-emerald-900/70 bg-emerald-950/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-emerald-300">
                <CheckCircle2 size={17} />
                <b>已加载 {loaded.dataset_count} 个数据集</b>
              </div>
              <Eligibility value={loaded.research_eligibility} />
            </div>
            <div className="mt-4 grid grid-cols-4 gap-3 text-sm">
              <div>
                <span>来源</span>
                <b>{sourceNames[loaded.source]}</b>
              </div>
              <div>
                <span>共同开始</span>
                <b>{loaded.common_date_range.start ?? "—"}</b>
              </div>
              <div>
                <span>共同结束</span>
                <b>{loaded.common_date_range.end ?? "—"}</b>
              </div>
              <div>
                <span>数据指纹</span>
                <b className="font-mono">{loaded.selection_id.slice(0, 12)}</b>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {loaded.datasets.map((dataset) => (
                <span
                  className="inline-flex items-center gap-1 border border-emerald-900 px-2 py-1 text-xs text-emerald-200"
                  key={dataset.dataset_id}
                >
                  <LockKeyhole size={12} /> {dataset.symbol} · {dataset.bar_count} bars
                </span>
              ))}
            </div>
            {loaded.warnings.length > 0 && (
              <ul className="mt-4 list-disc pl-5 text-xs text-amber-300">
                {loaded.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            )}
            {hasUnappliedChanges && (
              <p className="mt-4 border-t border-amber-900 pt-3 text-xs text-amber-300">
                上方勾选已经变化；当前仍使用这份已加载数据，重新点击“加载数据集”后才会替换。
              </p>
            )}
          </div>
        )}
      </section>

      {loaded ? (
        <BacktestSignalExplorer
          loaded={loaded}
          onBacktestComplete={(result) => {
            setLastResult(result);
            setShowResult(true);
          }}
        />
      ) : (
        <section className="panel backtest-workspace-panel border-dashed opacity-70">
          <PanelHeading
            title="④ K 线与信号预览"
            description="完成数据加载后，将在这里计算最新 B/S 与背离信号，并展示最近一年或两年的交互式 K 线。"
            meta="等待数据集"
          />
        </section>
      )}
    </div>
  );
}
