import { useEffect, useRef, useState } from "react";
import { LineChart as LineChartIcon } from "lucide-react";
import {
  AreaSeries,
  ColorType,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type LogicalRange,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { backtestSignalLabel } from "@/components/backtestSignalLabels";
import type { BacktestResult, BacktestTrade } from "@/components/backtestResultTypes";

type EquityPoint = { date: string; equity: number };
type DrawdownPoint = {
  date: string;
  strategy_drawdown: number;
  benchmark_drawdown: number;
};

type EquityScale = "nav" | "capital";

const capital = (value: number) => value.toLocaleString("zh-CN", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const netValue = (value: number) => value.toFixed(3);
const percent = (value: number) => `${(value * 100).toFixed(2)}%`;

const signalList = (signals: string[]) =>
  signals.map(backtestSignalLabel).join(" + ");

const operationMarkers = (
  trades: BacktestTrade[],
  openPosition: BacktestResult["open_position"],
): SeriesMarker<Time>[] => {
  const markers: SeriesMarker<Time>[] = [];
  for (const trade of trades) {
    markers.push({
      time: trade.entry_date,
      position: "belowBar",
      shape: "arrowUp",
      color: "#78a9ff",
      text: `买 ${signalList(trade.entry_signals)}`,
      size: 1.2,
    });
    const exitSignals = trade.exit_signals.length
      ? signalList(trade.exit_signals)
      : "最大持有";
    markers.push({
      time: trade.exit_date,
      position: "aboveBar",
      shape: "arrowDown",
      color: trade.net_return >= 0 ? "#42be65" : "#fa4d56",
      text: `卖 ${exitSignals} ${trade.net_return >= 0 ? "+" : ""}${percent(trade.net_return)}`,
      size: 1.2,
    });
  }
  if (openPosition) {
    markers.push({
      time: openPosition.entry_date,
      position: "belowBar",
      shape: "arrowUp",
      color: "#78a9ff",
      text: `买 ${signalList(openPosition.entry_signals)}`,
      size: 1.2,
    });
    if (openPosition.last_date !== openPosition.entry_date) {
      markers.push({
        time: openPosition.last_date,
        position: "aboveBar",
        shape: "circle",
        color: openPosition.unrealized_return >= 0 ? "#42be65" : "#fa4d56",
        text: `持仓 ${openPosition.unrealized_return >= 0 ? "+" : ""}${percent(openPosition.unrealized_return)}`,
        size: 1.1,
      });
    }
  }
  return markers.sort((left, right) => String(left.time).localeCompare(String(right.time)));
};

export function BacktestPerformanceCharts({
  equity,
  benchmark,
  drawdown,
  trades,
  openPosition,
}: {
  equity: EquityPoint[];
  benchmark: EquityPoint[];
  drawdown: DrawdownPoint[];
  trades: BacktestTrade[];
  openPosition: BacktestResult["open_position"];
}) {
  const equityHost = useRef<HTMLDivElement | null>(null);
  const drawdownHost = useRef<HTMLDivElement | null>(null);
  const [equityScale, setEquityScale] = useState<EquityScale>("nav");

  useEffect(() => {
    if (!equityHost.current || !drawdownHost.current) return;

    const css = getComputedStyle(document.documentElement);
    const colour = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback;
    const chartOptions = (host: HTMLDivElement) => ({
      width: Math.max(1, host.clientWidth),
      height: Math.max(1, host.clientHeight),
      layout: {
        background: {
          type: ColorType.Solid,
          color: colour("--ws-surface-1", "#161616"),
        },
        textColor: colour("--ws-text-muted", "#a8a8a8"),
      },
      grid: {
        vertLines: { color: colour("--ws-chart-grid", "#262626") },
        horzLines: { color: colour("--ws-chart-grid", "#262626") },
      },
      rightPriceScale: { borderColor: colour("--ws-border", "#393939") },
      timeScale: {
        borderColor: colour("--ws-border", "#393939"),
        timeVisible: false,
        rightOffset: 3,
        minBarSpacing: 1.5,
      },
      crosshair: { mode: 0 },
    });

    const equityChart = createChart(equityHost.current, chartOptions(equityHost.current));
    const drawdownChart = createChart(drawdownHost.current, chartOptions(drawdownHost.current));
    const strategyBase = equity.find((point) => point.equity !== 0)?.equity ?? 1;
    const benchmarkBase = benchmark.find((point) => point.equity !== 0)?.equity ?? 1;
    const equityFormatter = equityScale === "nav" ? netValue : capital;

    const strategyEquity = equityChart.addSeries(LineSeries, {
      title: equityScale === "nav" ? "策略净值" : "策略资金",
      color: "#22d3ee",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { type: "custom", formatter: equityFormatter },
    });
    const benchmarkEquity = equityChart.addSeries(LineSeries, {
      title: equityScale === "nav" ? "基准净值" : "基准资金",
      color: "#a1a1aa",
      lineWidth: 2,
      lineStyle: 2,
      priceLineVisible: false,
      priceFormat: { type: "custom", formatter: equityFormatter },
    });
    const strategyDrawdown = drawdownChart.addSeries(AreaSeries, {
      title: "策略回撤",
      lineColor: "#fa4d56",
      topColor: "#fa4d5650",
      bottomColor: "#fa4d5608",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { type: "custom", formatter: percent },
    });
    const benchmarkDrawdown = drawdownChart.addSeries(LineSeries, {
      title: "基准回撤",
      color: "#a1a1aa",
      lineWidth: 2,
      lineStyle: 2,
      priceLineVisible: false,
      priceFormat: { type: "custom", formatter: percent },
    });

    strategyEquity.setData(equity.map((point) => ({
      time: point.date,
      value: equityScale === "nav" ? point.equity / strategyBase : point.equity,
    })));
    benchmarkEquity.setData(benchmark.map((point) => ({
      time: point.date,
      value: equityScale === "nav" ? point.equity / benchmarkBase : point.equity,
    })));
    strategyDrawdown.setData(drawdown.map((point) => ({
      time: point.date,
      value: point.strategy_drawdown,
    })));
    benchmarkDrawdown.setData(drawdown.map((point) => ({
      time: point.date,
      value: point.benchmark_drawdown,
    })));
    const markers = createSeriesMarkers(
      strategyEquity,
      operationMarkers(trades, openPosition),
    );

    equityChart.timeScale().fitContent();
    drawdownChart.timeScale().fitContent();

    let synchronizing = false;
    const syncRange = (target: IChartApi) => (range: LogicalRange | null) => {
      if (!range || synchronizing) return;
      synchronizing = true;
      target.timeScale().setVisibleLogicalRange(range);
      synchronizing = false;
    };
    const syncToDrawdown = syncRange(drawdownChart);
    const syncToEquity = syncRange(equityChart);
    equityChart.timeScale().subscribeVisibleLogicalRangeChange(syncToDrawdown);
    drawdownChart.timeScale().subscribeVisibleLogicalRangeChange(syncToEquity);

    const resizeChart = (chart: IChartApi) =>
      new ResizeObserver(([entry]) => {
        chart.applyOptions({
          width: Math.max(1, Math.floor(entry.contentRect.width)),
          height: Math.max(1, Math.floor(entry.contentRect.height)),
        });
      });
    const equityResize = resizeChart(equityChart);
    const drawdownResize = resizeChart(drawdownChart);
    equityResize.observe(equityHost.current);
    drawdownResize.observe(drawdownHost.current);

    return () => {
      equityResize.disconnect();
      drawdownResize.disconnect();
      equityChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncToDrawdown);
      drawdownChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncToEquity);
      markers.detach();
      equityChart.remove();
      drawdownChart.remove();
    };
  }, [benchmark, drawdown, equity, equityScale, openPosition, trades]);

  return (
    <div className="backtest-result-charts grid gap-8">
      <section className="overflow-hidden border border-zinc-800 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <b className="inline-flex items-center gap-2 text-sm">
            <LineChartIcon size={15} className="text-cyan-300" />资金曲线
          </b>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-zinc-500">
              {equityScale === "nav" ? "纵轴：净值（起点 = 1.000）" : "纵轴：资金量"}
            </span>
            <div className="flex gap-1" role="group" aria-label="资金曲线纵轴">
              <button
                type="button"
                className={equityScale === "nav" ? "primary-button" : "secondary-button"}
                aria-pressed={equityScale === "nav"}
                onClick={() => setEquityScale("nav")}
              >
                净值
              </button>
              <button
                type="button"
                className={equityScale === "capital" ? "primary-button" : "secondary-button"}
                aria-pressed={equityScale === "capital"}
                onClick={() => setEquityScale("capital")}
              >
                资金量
              </button>
            </div>
          </div>
        </div>
        <div className="backtest-operation-legend flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
          <span><i className="mr-1 inline-block h-2 w-2 bg-blue-400" />蓝色：买入信号</span>
          <span><i className="mr-1 inline-block h-2 w-2 bg-emerald-500" />绿色：盈利退出</span>
          <span><i className="mr-1 inline-block h-2 w-2 bg-rose-500" />红色：亏损退出</span>
        </div>
        <div
          ref={equityHost}
          className="mt-3 h-[420px] w-full md:h-[520px]"
          role="img"
          aria-label="可缩放资金曲线"
        />
      </section>

      <section className="overflow-hidden border border-zinc-800 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <b className="text-sm">回撤曲线</b>
          <span className="text-xs text-zinc-500">距离历史净值高点 · 与资金曲线同步</span>
        </div>
        <div
          ref={drawdownHost}
          className="mt-3 h-[420px] w-full md:h-[520px]"
          role="img"
          aria-label="可缩放回撤曲线"
        />
      </section>
    </div>
  );
}
