import {
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { backtestSignalLabel } from "@/components/backtestSignalLabels";
import type { BacktestDataset, BacktestResult, BacktestRunRequest } from "@/components/backtestResultTypes";
import { PanelHeading } from "@/components/ui/workspace";

type SignalCatalogItem = {
  code: string;
  direction: "BUY" | "SELL";
  full_count: number;
};

const requestBacktest = async (request: BacktestRunRequest) => {
  const response = await fetch("/api/backtest/rules/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const payload = JSON.parse(text) as { detail?: string };
      message = payload.detail ?? text;
    } catch {
      // Preserve a non-JSON backend response for troubleshooting.
    }
    throw new Error(message);
  }
  return response.json() as Promise<BacktestResult>;
};

function SignalRulePicker({
  title,
  description,
  signals,
  selected,
  onToggle,
}: {
  title: string;
  description: string;
  signals: SignalCatalogItem[];
  selected: ReadonlySet<string>;
  onToggle: (code: string) => void;
}) {
  return (
    <fieldset className="border border-zinc-800 p-4">
      <legend className="px-2 text-sm font-semibold text-zinc-100">{title}</legend>
      <p className="mb-3 text-xs text-zinc-500">{description}</p>
      <div className="flex flex-wrap gap-2">
        {signals.map((signal) => {
          const checked = selected.has(signal.code);
          return (
            <button
              type="button"
              className={checked ? "primary-button" : "secondary-button"}
              key={signal.code}
              onClick={() => onToggle(signal.code)}
              aria-pressed={checked}
              title={`完整历史出现 ${signal.full_count} 次`}
            >
              {backtestSignalLabel(signal.code)} · {signal.full_count}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function BacktestRuleLab({
  dataset,
  signalCatalog,
  onComplete,
}: {
  dataset: BacktestDataset;
  signalCatalog: SignalCatalogItem[];
  onComplete: (result: BacktestResult) => void;
}) {
  const [buySignals, setBuySignals] = useState<Set<string>>(() => new Set());
  const [sellSignals, setSellSignals] = useState<Set<string>>(() => new Set());
  const [startDate, setStartDate] = useState(dataset.start_date);
  const [endDate, setEndDate] = useState(dataset.end_date);
  const [initialCapital, setInitialCapital] = useState(100_000);
  const [commissionBps, setCommissionBps] = useState(5);
  const [slippageBps, setSlippageBps] = useState(5);
  const [maxHoldingBars, setMaxHoldingBars] = useState(60);
  const run = useMutation({ mutationFn: requestBacktest, onSuccess: onComplete });
  const buyCandidates = useMemo(
    () => signalCatalog.filter((signal) => signal.direction === "BUY"),
    [signalCatalog],
  );
  const sellCandidates = useMemo(
    () => signalCatalog.filter((signal) => signal.direction === "SELL"),
    [signalCatalog],
  );

  const toggle = (
    setter: Dispatch<SetStateAction<Set<string>>>,
    code: string,
  ) => {
    setter((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const canRun = buySignals.size > 0
    && sellSignals.size > 0
    && startDate <= endDate
    && initialCapital > 0
    && commissionBps >= 0
    && slippageBps >= 0
    && maxHoldingBars > 0;
  const submit = () => {
    if (!canRun) return;
    run.mutate({
      dataset_id: dataset.dataset_id,
      buy_signals: [...buySignals],
      sell_signals: [...sellSignals],
      start_date: startDate,
      end_date: endDate,
      initial_capital: initialCapital,
      commission_bps_per_side: commissionBps,
      slippage_bps_per_side: slippageBps,
      max_holding_bars: maxHoldingBars,
    });
  };

  return (
    <div className="backtest-rule-lab border-t border-zinc-800">
      <PanelHeading
        title="⑤ 回测规则与交易引擎"
        description={`为 ${dataset.symbol} 选择规则。每侧勾选多个信号时采用“任一触发（OR）”。`}
        meta="单标的 · 只做多 · 次日开盘"
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <SignalRulePicker
          title="买入规则"
          description="空仓时，任一所选看多信号在可交易日开盘买入。"
          signals={buyCandidates}
          selected={buySignals}
          onToggle={(code) => toggle(setBuySignals, code)}
        />
        <SignalRulePicker
          title="卖出规则"
          description="持仓时，任一所选看空信号在可交易日开盘卖出。"
          signals={sellCandidates}
          selected={sellSignals}
          onToggle={(code) => toggle(setSellSignals, code)}
        />
      </div>

      <div className="backtest-rule-parameters grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <label className="text-xs text-zinc-400">
          开始日期
          <input className="terminal-input mt-1 w-full" type="date" value={startDate} min={dataset.start_date} max={endDate} onChange={(event) => setStartDate(event.target.value)} />
        </label>
        <label className="text-xs text-zinc-400">
          结束日期
          <input className="terminal-input mt-1 w-full" type="date" value={endDate} min={startDate} max={dataset.end_date} onChange={(event) => setEndDate(event.target.value)} />
        </label>
        <label className="text-xs text-zinc-400">
          初始资金
          <input className="terminal-input mt-1 w-full" type="number" min="1" step="1000" value={initialCapital} onChange={(event) => setInitialCapital(Number(event.target.value))} />
        </label>
        <label className="text-xs text-zinc-400">
          单边手续费（bp）
          <input className="terminal-input mt-1 w-full" type="number" min="0" max="500" step="1" value={commissionBps} onChange={(event) => setCommissionBps(Number(event.target.value))} />
        </label>
        <label className="text-xs text-zinc-400">
          单边滑点（bp）
          <input className="terminal-input mt-1 w-full" type="number" min="0" max="500" step="1" value={slippageBps} onChange={(event) => setSlippageBps(Number(event.target.value))} />
        </label>
        <label className="text-xs text-zinc-400">
          最大持有 K 线
          <input className="terminal-input mt-1 w-full" type="number" min="1" max="500" step="1" value={maxHoldingBars} onChange={(event) => setMaxHoldingBars(Number(event.target.value))} />
        </label>
      </div>

      <div className="backtest-rule-actions flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="primary-button inline-flex items-center gap-2"
          disabled={!canRun || run.isPending}
          onClick={submit}
        >
          <Play size={14} /> {run.isPending ? "正在运行回测…" : "运行回测"}
        </button>
        <span className="text-xs text-zinc-500">
          买入 {buySignals.size} 项 · 卖出 {sellSignals.size} 项；未触发卖出时最多持有 {maxHoldingBars} 根 K 线。
        </span>
      </div>

      {run.isError ? (
        <p className="error-banner mt-4">
          回测失败：{run.error instanceof Error ? run.error.message : "未知错误"}
        </p>
      ) : null}
    </div>
  );
}
