import { lazy, Suspense, useState } from "react";
import { CheckCircle2, Database, LockKeyhole, RefreshCw } from "lucide-react";
import { MarketCodeInput } from "@/components/MarketCodeInput";
import { BacktestSignalExplorer } from "@/components/BacktestSignalExplorer";
import type { BacktestResult } from "@/components/backtestResultTypes";
import { resolveMarketCode, type Market } from "@/lib/marketCode";
import { PanelHeading } from "@/components/ui/workspace";

const BacktestResultWorkspace = lazy(() => import("@/components/BacktestResultWorkspace").then(
  (module) => ({ default: module.BacktestResultWorkspace }),
));

type ResearchDataset = {
  dataset_id: string;
  symbol: string;
  timeframe: string;
  bar_count: number;
  start_date: string | null;
  end_date: string | null;
  adjustment: string;
  research_eligibility: string;
  quality: string;
  warnings: string[];
  snapshot_id: string | null;
  data_sha256: string | null;
  fetched_at: string | null;
};

type LoadedSelection = {
  selection_id: string;
  loaded_at: string;
  source: string;
  dataset_count: number;
  datasets: ResearchDataset[];
  common_date_range: { start: string | null; end: string | null };
  research_eligibility: string;
  warnings: string[];
  provider: "yahoo";
  cache_status: "HIT" | "FETCHED" | "REFRESHED";
  snapshot_fetched_at: string | null;
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

const eligibilityNames: Record<string, string> = {
  ELIGIBLE: "合格",
  LIMITED: "有限",
  INELIGIBLE: "不足",
};

const cacheNames: Record<LoadedSelection["cache_status"], string> = {
  HIT: "已复用今日行情",
  FETCHED: "已获取最新行情",
  REFRESHED: "已强制刷新行情",
};

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

function fetchedAtLabel(value: string | null) {
  if (!value) return "—";
  const compact = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(value);
  if (compact) {
    const [, year, month, day, hour, minute, second] = compact;
    return `${year}-${month}-${day} ${hour}:${minute}:${second} UTC`;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}

export function BacktestDataWorkspace() {
  const [market, setMarket] = useState<Market>("US");
  const [symbol, setSymbol] = useState("");
  const [loaded, setLoaded] = useState<LoadedSelection | null>(null);
  const [lastResult, setLastResult] = useState<BacktestResult | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadSymbol = async (refresh = false, explicitCode?: string) => {
    let code: string;
    try {
      code = explicitCode ?? resolveMarketCode(symbol, market);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const result = await request<LoadedSelection>("/api/backtest/symbol/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, refresh }),
      });
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

  const dataset = loaded?.datasets[0];

  return (
    <div className="backtest-workspace-stack grid">
      <section className="panel backtest-workspace-panel">
        <PanelHeading
          title="① 输入股票"
          description="输入股票代码后，系统会从 Yahoo 自动获取日线复权行情并加载到回测实验室。"
          meta="Yahoo 日线 · 2018 年至今"
        />
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void loadSymbol(false);
          }}
        >
          <label className="grid gap-2 text-xs text-zinc-400">
            市场与股票代码
            <span className="flex flex-wrap gap-2">
              <MarketCodeInput
                market={market}
                value={symbol}
                onMarketChange={setMarket}
                onValueChange={setSymbol}
                className="min-w-64"
              />
            </span>
          </label>
          <button
            className="primary-button inline-flex items-center gap-2"
            type="submit"
            disabled={loading || !symbol.trim()}
          >
            <Database size={15} />
            {loading ? "正在获取行情…" : "获取并加载"}
          </button>
        </form>
        <p className="mt-3 text-xs text-zinc-500">
          支持 AAPL、00700、600519 或完整市场代码；同一股票当天再次加载会复用已校验行情。
        </p>
        {loadError && <p className="error-banner mt-4">加载失败：{loadError}</p>}

        {dataset && loaded && (
          <div className="mt-5 border border-emerald-900/70 bg-emerald-950/20 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-emerald-300">
                <CheckCircle2 size={17} />
                <b>{dataset.symbol} 已加载</b>
                <span className="text-xs text-emerald-200/70">{cacheNames[loaded.cache_status]}</span>
              </div>
              <div className="flex items-center gap-2">
                <Eligibility value={loaded.research_eligibility} />
                <button
                  className="secondary-button inline-flex items-center gap-2"
                  type="button"
                  disabled={loading}
                  onClick={() => void loadSymbol(true, dataset.symbol)}
                >
                  <RefreshCw size={14} /> 刷新行情
                </button>
              </div>
            </div>
            <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-6">
              <div><span>行情来源</span><b>Yahoo</b></div>
              <div><span>日期范围</span><b>{dataset.start_date ?? "—"} 至 {dataset.end_date ?? "—"}</b></div>
              <div><span>K 线数量</span><b>{dataset.bar_count.toLocaleString()}</b></div>
              <div><span>行情时间</span><b>{fetchedAtLabel(loaded.snapshot_fetched_at)}</b></div>
              <div><span>数据质量</span><b>{dataset.quality}</b></div>
              <div><span>数据指纹</span><b className="font-mono">{loaded.selection_id.slice(0, 12)}</b></div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-emerald-200">
              <span className="inline-flex items-center gap-1 border border-emerald-900 px-2 py-1">
                <LockKeyhole size={12} /> 日线 · 复权行情 · 可复现快照
              </span>
            </div>
            {loaded.warnings.length > 0 && (
              <ul className="mt-4 list-disc pl-5 text-xs text-amber-300">
                {loaded.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
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
            title="② K 线与信号预览"
            description="输入股票并加载行情后，系统会自动计算 GPMA V1/V2 信号。"
            meta="等待股票"
          />
        </section>
      )}
    </div>
  );
}
