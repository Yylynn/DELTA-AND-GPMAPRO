import { useEffect, useRef, useState } from "react";
import { LineChart as LineChartIcon } from "lucide-react";
import {
  AreaSeries,
  ColorType,
  LineSeries,
  createChart,
  type IChartApi,
  type LogicalRange,
} from "lightweight-charts";
import {
  backtestSignalLabel,
  backtestSignalShortLabel,
} from "@/components/backtestSignalLabels";
import {
  DivergenceIcon,
  divergenceGlyphKind,
  type BacktestSignalVersion,
  type DivergenceGlyphKind,
} from "@/components/BacktestSignalGlyph";
import type { BacktestResult, BacktestTrade } from "@/components/backtestResultTypes";

type EquityPoint = { date: string; equity: number };
type DrawdownPoint = {
  date: string;
  strategy_drawdown: number;
  benchmark_drawdown: number;
};

type EquityScale = "nav" | "capital";
type OperationPosition = "above" | "below";

type OperationPoint = {
  key: string;
  date: string;
  position: OperationPosition;
  color: string;
  signals: Array<{
    label?: string;
    glyph?: DivergenceGlyphKind;
    version: BacktestSignalVersion;
  }>;
  description: string;
};

type OperationOverlay = {
  key: string;
  x: number;
  y: number;
  items: Array<{
    key: string;
    color: string;
    label?: string;
    glyph?: DivergenceGlyphKind;
    version: BacktestSignalVersion;
    description: string;
  }>;
};

const capital = (value: number) => value.toLocaleString("zh-CN", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const netValue = (value: number) => value.toFixed(3);
const percent = (value: number) => `${(value * 100).toFixed(2)}%`;

const signalList = (signals: string[]) =>
  signals.map(backtestSignalLabel).join(" + ");

const compactSignal = (signal: string) => {
  const version: BacktestSignalVersion = signal.startsWith("V2_") ? "2.0" : "1.0";
  const glyph = divergenceGlyphKind(signal, version);
  return glyph
    ? { glyph, version }
    : { label: backtestSignalShortLabel(signal), version };
};

const operationPoints = (
  trades: BacktestTrade[],
  openPosition: BacktestResult["open_position"],
): OperationPoint[] => {
  const points: OperationPoint[] = [];
  trades.forEach((trade, index) => {
    points.push({
      key: `trade-${index}-entry`,
      date: trade.entry_date,
      position: "below",
      color: "#78a9ff",
      signals: trade.entry_signals.map(compactSignal),
      description: `买入 · ${signalList(trade.entry_signals)}`,
    });
    const exitSignals = trade.exit_signals.length
      ? signalList(trade.exit_signals)
      : "最大持有";
    const profitable = trade.net_return >= 0;
    points.push({
      key: `trade-${index}-exit`,
      date: trade.exit_date,
      position: "above",
      color: trade.net_return >= 0 ? "#42be65" : "#fa4d56",
      signals: trade.exit_signals.length
        ? trade.exit_signals.map(compactSignal)
        : [{ label: "退出", version: "1.0" }],
      description: `${profitable ? "盈利退出" : "亏损退出"} · ${exitSignals} · ${profitable ? "+" : ""}${percent(trade.net_return)}`,
    });
  });
  if (openPosition) {
    points.push({
      key: "open-position-entry",
      date: openPosition.entry_date,
      position: "below",
      color: "#78a9ff",
      signals: openPosition.entry_signals.map(compactSignal),
      description: `买入 · ${signalList(openPosition.entry_signals)}`,
    });
  }
  return points.sort((left, right) => left.date.localeCompare(right.date));
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
  const [operationOverlays, setOperationOverlays] = useState<OperationOverlay[]>([]);

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

    equityChart.timeScale().fitContent();
    drawdownChart.timeScale().fitContent();

    const equityByDate = new Map(equity.map((point) => [point.date, point.equity]));
    const points = operationPoints(trades, openPosition);
    let overlayFrame = 0;
    const updateOperationOverlays = () => {
      const groups = new Map<string, OperationPoint[]>();
      for (const point of points) {
        const key = `${point.date}:${point.position}`;
        groups.set(key, [...(groups.get(key) ?? []), point]);
      }
      const overlays = [...groups.entries()].flatMap(([key, grouped]) => {
        const first = grouped[0];
        const rawEquity = equityByDate.get(first.date);
        if (rawEquity == null || !equityHost.current) return [];
        const plottedEquity = equityScale === "nav" ? rawEquity / strategyBase : rawEquity;
        const x = equityChart.timeScale().timeToCoordinate(first.date);
        const anchorY = strategyEquity.priceToCoordinate(plottedEquity);
        if (x == null || anchorY == null || x < 0 || x > equityHost.current.clientWidth) return [];
        const displayX = Math.max(22, Math.min(equityHost.current.clientWidth - 36, x));
        const items = grouped.flatMap((point) => point.signals.map((signal, index) => ({
          key: `${point.key}-${index}`,
          color: point.color,
          ...signal,
          description: point.description,
        })));
        const rowHeight = 22;
        const stackHeight = items.length * rowHeight;
        const unclampedY = first.position === "below"
          ? anchorY + 9
          : anchorY - 9 - stackHeight;
        const y = Math.max(4, Math.min(equityHost.current.clientHeight - stackHeight - 28, unclampedY));
        return [{ key, x: displayX, y, items }];
      });
      setOperationOverlays(overlays);
    };
    const scheduleOperationOverlayUpdate = () => {
      cancelAnimationFrame(overlayFrame);
      overlayFrame = requestAnimationFrame(updateOperationOverlays);
    };
    equityChart.timeScale().subscribeVisibleLogicalRangeChange(scheduleOperationOverlayUpdate);
    scheduleOperationOverlayUpdate();

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

    const resizeChart = (chart: IChartApi, afterResize?: () => void) =>
      new ResizeObserver(([entry]) => {
        chart.applyOptions({
          width: Math.max(1, Math.floor(entry.contentRect.width)),
          height: Math.max(1, Math.floor(entry.contentRect.height)),
        });
        afterResize?.();
      });
    const equityResize = resizeChart(equityChart, scheduleOperationOverlayUpdate);
    const drawdownResize = resizeChart(drawdownChart);
    equityResize.observe(equityHost.current);
    drawdownResize.observe(drawdownHost.current);

    return () => {
      equityResize.disconnect();
      drawdownResize.disconnect();
      cancelAnimationFrame(overlayFrame);
      equityChart.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleOperationOverlayUpdate);
      equityChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncToDrawdown);
      drawdownChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncToEquity);
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
        <div className="relative mt-3 h-[420px] w-full md:h-[520px]">
          <div
            ref={equityHost}
            className="h-full w-full"
            role="img"
            aria-label="可缩放资金曲线"
          />
          <div
            className="pointer-events-none absolute inset-0 overflow-hidden"
            aria-hidden="true"
            style={{ zIndex: 3 }}
          >
            {operationOverlays.map((marker) => (
              <span
                className="absolute -translate-x-1/2 drop-shadow-[0_1px_1px_rgba(0,0,0,0.9)]"
                key={marker.key}
                style={{
                  alignItems: "center",
                  display: "flex",
                  flexDirection: "column",
                  gap: 0,
                  left: marker.x,
                  top: marker.y,
                }}
              >
                {marker.items.map((item) => (
                  <span
                    key={item.key}
                    title={item.description}
                    style={{
                      alignItems: "center",
                      color: item.color,
                      display: "flex",
                      fontSize: 12,
                      fontWeight: 700,
                      height: 22,
                      justifyContent: "center",
                      lineHeight: "22px",
                      pointerEvents: "auto",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {item.glyph
                      ? <DivergenceIcon kind={item.glyph} version={item.version} color={item.color} />
                      : item.label}
                  </span>
                ))}
              </span>
            ))}
          </div>
        </div>
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
