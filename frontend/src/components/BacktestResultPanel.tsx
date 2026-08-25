import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, Fingerprint } from "lucide-react";
import { BacktestPerformanceCharts } from "@/components/BacktestPerformanceCharts";
import { backtestSignalLabel } from "@/components/backtestSignalLabels";
import type {
  BacktestResult,
  BacktestRunRequest,
  BacktestTrade,
} from "@/components/backtestResultTypes";
import { PanelHeading } from "@/components/ui/workspace";

type ResultTab = "overview" | "monthly" | "trades" | "audit";
type TradeFilter = "ALL" | "SELL_SIGNAL" | "MAX_HOLD";

const PAGE_SIZE = 20;
const moneyFormatter = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const pct = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;

const number = (value: number | null | undefined, digits = 2) =>
  value == null ? "—" : value.toFixed(digits);

const money = (value: number) => moneyFormatter.format(value);

const exportResult = async ({ request, expectedFingerprint }: {
  request: BacktestRunRequest;
  expectedFingerprint: string;
}) => {
  const response = await fetch("/api/backtest/rules/export.csv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await response.text());
  const exportedFingerprint = response.headers.get("X-Backtest-Fingerprint");
  if (exportedFingerprint !== expectedFingerprint) {
    throw new Error("数据或规则已变化，导出指纹与当前结果不一致，请重新运行回测。");
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? "backtest-result.csv";
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return filename;
};

function MetricCard({ label, value, tone = "normal" }: {
  label: string;
  value: string;
  tone?: "normal" | "positive" | "negative";
}) {
  const colour = tone === "positive"
    ? "text-emerald-300"
    : tone === "negative"
      ? "text-rose-300"
      : "text-cyan-200";
  return (
    <div className="border border-zinc-800 p-3">
      <span className="text-xs text-zinc-500">{label}</span>
      <b className={`mt-1 block text-sm ${colour}`}>{value}</b>
    </div>
  );
}

function TradeSummary({ title, trade }: { title: string; trade: BacktestTrade | null }) {
  return (
    <div className="border border-zinc-800 p-3">
      <span className="text-xs text-zinc-500">{title}</span>
      {trade ? (
        <div className="mt-2 text-sm">
          <b className={trade.net_return >= 0 ? "text-emerald-300" : "text-rose-300"}>{pct(trade.net_return)}</b>
          <span className="ml-2 text-xs text-zinc-500">{trade.entry_date} → {trade.exit_date}</span>
          <p className="mt-1 text-xs text-zinc-400">{trade.entry_signals.map(backtestSignalLabel).join("、")}</p>
        </div>
      ) : <b className="mt-2 block text-sm">—</b>}
    </div>
  );
}

export function BacktestResultPanel({ result, stale }: {
  result: BacktestResult;
  stale: boolean;
}) {
  const [tab, setTab] = useState<ResultTab>("overview");
  const [tradeFilter, setTradeFilter] = useState<TradeFilter>("ALL");
  const [page, setPage] = useState(0);
  const download = useMutation({ mutationFn: exportResult });
  const filteredTrades = useMemo(
    () => result.closed_trades.filter((trade) => tradeFilter === "ALL" || trade.exit_reason === tradeFilter),
    [result.closed_trades, tradeFilter],
  );
  const pageCount = Math.max(1, Math.ceil(filteredTrades.length / PAGE_SIZE));
  const visibleTrades = filteredTrades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const exportRequest: BacktestRunRequest = {
    dataset_id: result.dataset.dataset_id,
    ...result.parameters,
  };

  const changeTradeFilter = (next: TradeFilter) => {
    setTradeFilter(next);
    setPage(0);
  };

  return (
    <section className="backtest-result-content border-t border-zinc-800" aria-label="回测结果">
      <PanelHeading
        title="⑥ 回测结果"
        description={`${result.dataset.symbol} · ${result.period.start} 至 ${result.period.end} · ${result.period.bar_count} 根 K 线`}
        meta={`运行指纹 ${result.run_fingerprint.slice(0, 12)}`}
      />
      {stale ? (
        <p className="mb-4 border border-amber-900/70 bg-amber-950/20 p-3 text-xs text-amber-200">
          当前规则或参数已经改变；本页仍保留上一次结果，重新运行后才会替换。
        </p>
      ) : null}

      <div className="backtest-result-toolbar flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="回测结果视图">
          {([
            ["overview", "绩效总览"],
            ["monthly", "月度表现"],
            ["trades", `交易明细 ${result.closed_trades.length}`],
            ["audit", "运行审计"],
          ] as const).map(([value, label]) => (
            <button
              type="button"
              role="tab"
              aria-selected={tab === value}
              className={tab === value ? "primary-button" : "secondary-button"}
              key={value}
              onClick={() => setTab(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="secondary-button inline-flex items-center gap-2"
          disabled={download.isPending}
          onClick={() => download.mutate({
            request: exportRequest,
            expectedFingerprint: result.run_fingerprint,
          })}
        >
          <Download size={14} /> {download.isPending ? "正在导出…" : "导出操作资金 CSV"}
        </button>
      </div>
      {download.isError ? <p className="error-banner mb-4">导出失败：{download.error instanceof Error ? download.error.message : "未知错误"}</p> : null}
      {download.isSuccess ? <p className="mb-4 text-xs text-emerald-300">已导出：{download.data}</p> : null}

      {tab === "overview" ? (
        <div role="tabpanel">
          <div className="backtest-result-metrics grid gap-5 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="策略总收益" value={pct(result.metrics.total_return)} tone={result.metrics.total_return >= 0 ? "positive" : "negative"} />
            <MetricCard label="买入持有" value={pct(result.benchmark_metrics.total_return)} />
            <MetricCard label="超额收益" value={pct(result.metrics.total_return - result.benchmark_metrics.total_return)} tone={result.metrics.total_return >= result.benchmark_metrics.total_return ? "positive" : "negative"} />
            <MetricCard label="最大回撤" value={pct(result.metrics.max_drawdown)} tone="negative" />
            <MetricCard label="Sharpe" value={number(result.metrics.sharpe)} />
            <MetricCard label="已平仓交易" value={String(result.metrics.trade_count)} />
            <MetricCard label="胜率" value={pct(result.metrics.win_rate)} />
            <MetricCard label="平均每笔" value={pct(result.metrics.average_trade_return)} />
            <MetricCard label="Profit Factor" value={number(result.metrics.profit_factor)} />
            <MetricCard label="资金暴露" value={pct(result.metrics.exposure_rate)} />
          </div>

          <BacktestPerformanceCharts
            equity={result.equity_curve}
            benchmark={result.benchmark_curve}
            drawdown={result.drawdown_curve}
            trades={result.closed_trades}
            openPosition={result.open_position}
          />

          <div className="backtest-result-analysis grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <TradeSummary title="最佳交易" trade={result.trade_analysis.best_trade} />
            <TradeSummary title="最差交易" trade={result.trade_analysis.worst_trade} />
            <MetricCard label="平均持有" value={result.trade_analysis.average_holding_bars == null ? "—" : `${result.trade_analysis.average_holding_bars.toFixed(1)} bars`} />
            <MetricCard label="最大连续亏损" value={`${result.trade_analysis.max_consecutive_losses} 笔`} />
            <MetricCard label="平均盈利" value={pct(result.trade_analysis.average_win)} />
            <MetricCard label="平均亏损" value={pct(result.trade_analysis.average_loss)} />
            <MetricCard label="平均盈亏比" value={number(result.trade_analysis.payoff_ratio)} />
            <MetricCard label="信号退出 / 到期退出" value={`${result.trade_analysis.exit_reason_counts.SELL_SIGNAL ?? 0} / ${result.trade_analysis.exit_reason_counts.MAX_HOLD ?? 0}`} />
          </div>
          {result.open_position ? (
            <p className="mt-4 border border-amber-900/70 bg-amber-950/20 p-3 text-xs text-amber-200">
              区间结束时仍有持仓：{result.open_position.entry_date} 由 {result.open_position.entry_signals.map(backtestSignalLabel).join("、")} 买入，按 {result.open_position.last_date} 收盘计未实现收益 {pct(result.open_position.unrealized_return)}；不计入已平仓胜率。
            </p>
          ) : null}
        </div>
      ) : null}

      {tab === "monthly" ? (
        <div className="overflow-x-auto border border-zinc-800" role="tabpanel">
          <table>
            <thead><tr><th>月份</th><th>策略收益</th><th>买入持有</th><th>超额收益</th></tr></thead>
            <tbody>{result.monthly_returns.map((row) => (
              <tr key={row.month}>
                <td>{row.month}</td>
                <td className={row.strategy_return >= 0 ? "text-emerald-300" : "text-rose-300"}>{pct(row.strategy_return)}</td>
                <td>{pct(row.benchmark_return)}</td>
                <td className={row.excess_return >= 0 ? "text-emerald-300" : "text-rose-300"}>{pct(row.excess_return)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : null}

      {tab === "trades" ? (
        <div role="tabpanel">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              {(["ALL", "SELL_SIGNAL", "MAX_HOLD"] as const).map((value) => (
                <button type="button" className={tradeFilter === value ? "primary-button" : "secondary-button"} key={value} onClick={() => changeTradeFilter(value)}>
                  {value === "ALL" ? "全部" : value === "SELL_SIGNAL" ? "信号退出" : "最大持有"}
                </button>
              ))}
            </div>
            <span className="text-xs text-zinc-500">{filteredTrades.length} 笔 · 第 {page + 1} / {pageCount} 页</span>
          </div>
          <div className="overflow-x-auto border border-zinc-800">
            <table>
              <thead><tr><th>入场信号 / 确认日</th><th>买入</th><th>退出信号</th><th>卖出</th><th>持有</th><th>净收益 / 盈亏</th><th>MFE / MAE</th></tr></thead>
              <tbody>{visibleTrades.length ? visibleTrades.map((trade) => (
                <tr key={`${trade.entry_date}-${trade.exit_date}`}>
                  <td>{trade.entry_signals.map(backtestSignalLabel).join("、")}<span className="block text-xs text-zinc-500">{trade.entry_signal_date}</span></td>
                  <td>{trade.entry_date}<span className="block text-xs text-zinc-500">{trade.entry_price.toFixed(2)}</span></td>
                  <td>{trade.exit_signals.length ? trade.exit_signals.map(backtestSignalLabel).join("、") : "最大持有"}<span className="block text-xs text-zinc-500">{trade.exit_signal_date ?? "—"}</span></td>
                  <td>{trade.exit_date}<span className="block text-xs text-zinc-500">{trade.exit_price.toFixed(2)}</span></td>
                  <td>{trade.holding_bars} bars</td>
                  <td className={trade.net_return >= 0 ? "text-emerald-300" : "text-rose-300"}>{pct(trade.net_return)}<span className="block text-xs">{money(trade.pnl)}</span></td>
                  <td>{pct(trade.mfe)} / {pct(trade.mae)}</td>
                </tr>
              )) : <tr><td colSpan={7} className="py-8 text-center text-zinc-500">当前筛选没有交易。</td></tr>}</tbody>
            </table>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" className="secondary-button" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>上一页</button>
            <button type="button" className="secondary-button" disabled={page + 1 >= pageCount} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>下一页</button>
          </div>
        </div>
      ) : null}

      {tab === "audit" ? (
        <div className="grid gap-4 xl:grid-cols-2" role="tabpanel">
          <section className="border border-zinc-800 p-4">
            <b className="inline-flex items-center gap-2 text-sm"><Fingerprint size={15} className="text-cyan-300" />数据与运行身份</b>
            <dl className="mt-3 grid grid-cols-[120px_1fr] gap-2 text-xs">
              <dt className="text-zinc-500">数据集</dt><dd>{result.dataset.dataset_id}</dd>
              <dt className="text-zinc-500">标的 / 来源</dt><dd>{result.dataset.symbol} · {result.dataset.source ?? "—"}</dd>
              <dt className="text-zinc-500">数据范围</dt><dd>{result.period.start} 至 {result.period.end} · {result.period.bar_count} bars</dd>
              <dt className="text-zinc-500">复权</dt><dd>{result.dataset.adjustment ?? "未记录"}</dd>
              <dt className="text-zinc-500">数据 SHA256</dt><dd className="break-all font-mono">{result.dataset.data_sha256 ?? "—"}</dd>
              <dt className="text-zinc-500">运行指纹</dt><dd className="break-all font-mono">{result.run_fingerprint}</dd>
            </dl>
          </section>
          <section className="border border-zinc-800 p-4">
            <b className="text-sm">规则与成本</b>
            <dl className="mt-3 grid grid-cols-[120px_1fr] gap-2 text-xs">
              <dt className="text-zinc-500">买入 OR</dt><dd>{result.parameters.buy_signals.map(backtestSignalLabel).join("、")}</dd>
              <dt className="text-zinc-500">卖出 OR</dt><dd>{result.parameters.sell_signals.map(backtestSignalLabel).join("、")}</dd>
              <dt className="text-zinc-500">初始资金</dt><dd>{money(result.parameters.initial_capital)}</dd>
              <dt className="text-zinc-500">单边手续费</dt><dd>{result.parameters.commission_bps_per_side} bp</dd>
              <dt className="text-zinc-500">单边滑点</dt><dd>{result.parameters.slippage_bps_per_side} bp</dd>
              <dt className="text-zinc-500">最大持有</dt><dd>{result.parameters.max_holding_bars} bars</dd>
            </dl>
          </section>
          <section className="border border-zinc-800 p-4 xl:col-span-2">
            <b className="text-sm">引擎假设</b>
            <ul className="mt-3 grid gap-2 text-xs text-zinc-400 md:grid-cols-2">
              {Object.entries(result.assumptions).map(([key, value]) => <li key={key}><span className="font-mono text-zinc-500">{key}</span> · {value}</li>)}
            </ul>
          </section>
        </div>
      ) : null}
    </section>
  );
}
