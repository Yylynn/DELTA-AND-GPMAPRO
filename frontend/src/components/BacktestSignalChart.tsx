import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

export type PreviewBar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type SignalEvent = {
  code: string;
  family: "B" | "S" | "DIVERGENCE" | "DELTA";
  direction: "BUY" | "SELL";
  signal_date: string;
  marker_date: string;
  tradable_on: string | null;
  actual_date: string;
  confirmed_on: string | null;
  price: number;
  structure_price: number | null;
};

const markerStyle = (event: SignalEvent) => {
  if (event.code === "BOTTOM_FACE")
    return { key: "BOTTOM_FACE", position: "belowBar" as const, shape: "circle" as const, color: "#f1c21b", label: "☺" };
  if (event.code === "TOP_FACE")
    return { key: "TOP_FACE", position: "aboveBar" as const, shape: "circle" as const, color: "#a56eff", label: "☹" };
  if (event.code === "BOTTOM_ARROW_2")
    return { key: "BOTTOM_ARROW_2", position: "belowBar" as const, shape: "arrowUp" as const, color: "#33b1ff", label: "底部 2" };
  if (event.code === "TOP_ARROW_2")
    return { key: "TOP_ARROW_2", position: "aboveBar" as const, shape: "arrowDown" as const, color: "#ff832b", label: "顶部 2" };
  if (event.code === "DELTA_LOW")
    return { key: "DELTA_LOW", position: "belowBar" as const, shape: "circle" as const, color: "#be95ff", label: "Δ LOW" };
  if (event.code === "DELTA_HIGH")
    return { key: "DELTA_HIGH", position: "aboveBar" as const, shape: "circle" as const, color: "#ff832b", label: "Δ HIGH" };
  if (event.direction === "BUY")
    return { key: "B", position: "belowBar" as const, shape: "arrowUp" as const, color: "#42be65", label: event.code };
  return { key: "S", position: "aboveBar" as const, shape: "arrowDown" as const, color: "#fa4d56", label: event.code };
};

const buildMarkers = (
  events: SignalEvent[],
  visibleSignals: ReadonlySet<string>,
): SeriesMarker<Time>[] => {
  const groups = new Map<string, { events: SignalEvent[]; style: ReturnType<typeof markerStyle> }>();
  for (const event of events) {
    if (!visibleSignals.has(event.code)) continue;
    const style = markerStyle(event);
    const key = `${event.marker_date}:${style.key}`;
    const current = groups.get(key);
    if (current) current.events.push(event);
    else groups.set(key, { events: [event], style });
  }
  return [...groups.values()]
    .map(({ events: grouped, style }) => ({
      time: grouped[0].marker_date,
      position: style.position,
      shape: style.shape,
      color: style.color,
      text: style.key === "B" || style.key === "S"
        ? grouped.map((event) => event.code).join(" · ")
        : style.label,
      size: style.key.endsWith("FACE") ? 1.5 : style.key.startsWith("DELTA") ? 1.2 : 1,
    }))
    .sort((left, right) => String(left.time).localeCompare(String(right.time)));
};

const timeKey = (time: Time | undefined): string | null => {
  if (time == null) return null;
  if (typeof time === "string") return time;
  if (typeof time === "number") return new Date(time * 1000).toISOString().slice(0, 10);
  return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
};

export function BacktestSignalChart({
  bars,
  events,
  visibleSignals,
}: {
  bars: PreviewBar[];
  events: SignalEvent[];
  visibleSignals: ReadonlySet<string>;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const [hoverDate, setHoverDate] = useState<string | null>(null);
  const barMap = useMemo(() => new Map(bars.map((bar) => [bar.date, bar])), [bars]);
  const visibleEventsByDate = useMemo(() => {
    const result = new Map<string, SignalEvent[]>();
    for (const event of events) {
      if (!visibleSignals.has(event.code)) continue;
      const current = result.get(event.marker_date) ?? [];
      current.push(event);
      result.set(event.marker_date, current);
    }
    return result;
  }, [events, visibleSignals]);

  useEffect(() => {
    if (!host.current) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
    const instance = createChart(host.current, {
      width: host.current.clientWidth,
      height: 540,
      layout: {
        background: { type: ColorType.Solid, color: color("--ws-surface-1", "#161616") },
        textColor: color("--ws-text-muted", "#a8a8a8"),
      },
      grid: {
        vertLines: { color: color("--ws-chart-grid", "#262626") },
        horzLines: { color: color("--ws-chart-grid", "#262626") },
      },
      rightPriceScale: { borderColor: color("--ws-border", "#393939") },
      timeScale: { borderColor: color("--ws-border", "#393939"), timeVisible: false },
      crosshair: { mode: 0 },
    });
    const candleSeries = instance.addSeries(CandlestickSeries, {
      upColor: "#fa4d56",
      downColor: "#42be65",
      borderUpColor: "#fa4d56",
      borderDownColor: "#42be65",
      wickUpColor: "#fa4d56",
      wickDownColor: "#42be65",
    });
    candleSeries.priceScale().applyOptions({ scaleMargins: { top: .08, bottom: .2 } });
    const volumeSeries = instance.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: .84, bottom: 0 } });
    chart.current = instance;
    candles.current = candleSeries;
    volume.current = volumeSeries;
    markers.current = createSeriesMarkers(candleSeries, []);

    const resize = new ResizeObserver(([entry]) => {
      instance.applyOptions({ width: Math.max(320, Math.floor(entry.contentRect.width)) });
    });
    resize.observe(host.current);
    return () => {
      resize.disconnect();
      markers.current?.detach();
      instance.remove();
      chart.current = null;
      candles.current = null;
      volume.current = null;
      markers.current = null;
    };
  }, []);

  useEffect(() => {
    candles.current?.setData(bars.map((bar) => ({
      time: bar.date,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })));
    volume.current?.setData(bars.map((bar) => ({
      time: bar.date,
      value: bar.volume,
      color: bar.close >= bar.open ? "#fa4d5670" : "#42be6570",
    })));
    chart.current?.timeScale().fitContent();
  }, [bars]);

  useEffect(() => {
    markers.current?.setMarkers(buildMarkers(events, visibleSignals));
  }, [events, visibleSignals]);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const handleMove = (parameter: MouseEventParams<Time>) => {
      const date = timeKey(parameter.time);
      setHoverDate(date && barMap.has(date) ? date : null);
    };
    instance.subscribeCrosshairMove(handleMove);
    return () => instance.unsubscribeCrosshairMove(handleMove);
  }, [barMap, visibleEventsByDate]);

  const focus = (hoverDate ? barMap.get(hoverDate) : undefined) ?? bars.at(-1);
  const hoverEvents = hoverDate ? visibleEventsByDate.get(hoverDate) ?? [] : [];
  return (
    <div className="overflow-hidden border border-zinc-800 bg-zinc-950">
      <div className="flex min-h-14 flex-wrap items-center gap-x-5 gap-y-1 border-b border-zinc-800 px-4 py-2 text-xs">
        <b className="text-zinc-100">{focus?.date ?? "—"}</b>
        <span>开 {focus?.open.toFixed(2) ?? "—"}</span>
        <span>高 {focus?.high.toFixed(2) ?? "—"}</span>
        <span>低 {focus?.low.toFixed(2) ?? "—"}</span>
        <span>收 {focus?.close.toFixed(2) ?? "—"}</span>
        <span>量 {focus?.volume.toLocaleString() ?? "—"}</span>
        <span className="text-cyan-200">
          {hoverEvents.length
            ? hoverEvents.map((event) => `${event.code}（信号 ${event.signal_date} · 可交易 ${event.tradable_on ?? "待下一根 K 线"}）`).join("；")
            : "移动十字线查看当日信号"}
        </span>
      </div>
      <div ref={host} className="w-full" role="img" aria-label="回测数据 K 线、成交量与信号预览" />
    </div>
  );
}
