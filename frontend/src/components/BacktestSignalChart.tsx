import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import {
  backtestSignalLabel,
  backtestSignalShortLabel,
} from "@/components/backtestSignalLabels";

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
  version: "1.0" | "2.0";
  family: "B" | "S" | "DIVERGENCE";
  direction: "BUY" | "SELL";
  signal_date: string;
  marker_date: string;
  tradable_on: string | null;
  actual_date: string;
  confirmed_on: string | null;
  price: number;
  structure_price: number | null;
};

const V1_DIVERGENCE_COLOR = "#33b1ff";
const V2_DIVERGENCE_COLOR = "#be95ff";

type DivergenceGlyphKind = "happy" | "sad" | "thin-up" | "thin-down" | "wide-up" | "wide-down" | "triangle-up" | "triangle-down";

const divergenceGlyphKind = (event: SignalEvent): DivergenceGlyphKind => {
  if (event.code.endsWith("_BOTTOM_FACE")) return "happy";
  if (event.code.endsWith("_TOP_FACE")) return "sad";
  if (event.code.endsWith("_BOTTOM_ARROW_3")) return "wide-up";
  if (event.code.endsWith("_TOP_ARROW_3")) return "wide-down";
  if (event.code.endsWith("_BOTTOM_ARROW_2")) return event.version === "1.0" ? "thin-up" : "triangle-up";
  return event.version === "1.0" ? "thin-down" : "triangle-down";
};

function DivergenceIcon({
  kind,
  version,
  size = 22,
}: {
  kind: DivergenceGlyphKind;
  version: SignalEvent["version"];
  size?: number;
}) {
  const color = version === "1.0" ? V1_DIVERGENCE_COLOR : V2_DIVERGENCE_COLOR;
  if (kind === "happy" || kind === "sad") {
    const filled = version === "2.0";
    const featureColor = filled ? "#161b22" : color;
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill={filled ? color : "#161b22"} stroke={color} strokeWidth="2" />
        <circle cx="9" cy="10" r="1.25" fill={featureColor} />
        <circle cx="15" cy="10" r="1.25" fill={featureColor} />
        <path
          d={kind === "happy" ? "M7.5 14c1.2 2 2.7 3 4.5 3s3.3-1 4.5-3" : "M7.5 17c1.2-2 2.7-3 4.5-3s3.3 1 4.5 3"}
          stroke={featureColor}
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  if (kind === "thin-up" || kind === "thin-down") {
    const up = kind === "thin-up";
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d={up ? "M12 21V4M5 11l7-7 7 7" : "M12 3v17M5 13l7 7 7-7"}
          stroke={color}
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (kind === "wide-up" || kind === "wide-down") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill={color} aria-hidden="true">
        <path d={kind === "wide-up" ? "M12 2 22 12h-6v10H8V12H2L12 2Z" : "M8 2h8v10h6L12 22 2 12h6V2Z"} />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={color} aria-hidden="true">
      <path d={kind === "triangle-up" ? "M12 3 22 20H2L12 3Z" : "M2 4h20L12 21 2 4Z"} />
    </svg>
  );
}

type SignalOverlayItem = {
  key: string;
  version: SignalEvent["version"];
  label?: string;
  glyph?: DivergenceGlyphKind;
  color: string;
};

type SignalOverlay = {
  key: string;
  items: SignalOverlayItem[];
  x: number;
  y: number;
};

const signalEventOrder = (event: SignalEvent) => {
  const familyOrder = event.family === "DIVERGENCE" ? 10 : 0;
  const versionOrder = event.version === "1.0" ? 0 : 1;
  return familyOrder + versionOrder;
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
  const [hoverDate, setHoverDate] = useState<string | null>(null);
  const [signalOverlays, setSignalOverlays] = useState<SignalOverlay[]>([]);
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
  const visibleChartEvents = useMemo(
    () => events.filter((event) => visibleSignals.has(event.code)),
    [events, visibleSignals],
  );

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

    const resize = new ResizeObserver(([entry]) => {
      instance.applyOptions({ width: Math.max(320, Math.floor(entry.contentRect.width)) });
    });
    resize.observe(host.current);
    return () => {
      resize.disconnect();
      instance.remove();
      chart.current = null;
      candles.current = null;
      volume.current = null;
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
    const instance = chart.current;
    const candleSeries = candles.current;
    const chartHost = host.current;
    if (!instance || !candleSeries || !chartHost) return;
    let animationFrame = 0;
    const update = () => {
      const groups = new Map<string, SignalEvent[]>();
      for (const event of visibleChartEvents) {
        const key = `${event.marker_date}:${event.direction}`;
        groups.set(key, [...(groups.get(key) ?? []), event]);
      }
      const overlays = [...groups.entries()].flatMap(([key, grouped]) => {
        const first = grouped[0];
        const bar = barMap.get(first.marker_date);
        const x = instance.timeScale().timeToCoordinate(first.marker_date);
        const anchorPrice = bar ? (first.direction === "BUY" ? bar.low : bar.high) : first.price;
        const anchorY = candleSeries.priceToCoordinate(anchorPrice);
        if (x == null || anchorY == null || x < 0 || x > chartHost.clientWidth) return [];
        const uniqueEvents = [...new Map(grouped.map((event) => [event.code, event])).values()]
          .sort((left, right) => signalEventOrder(left) - signalEventOrder(right) || left.code.localeCompare(right.code));
        if (first.direction === "SELL") uniqueEvents.reverse();
        const items = uniqueEvents.map((event): SignalOverlayItem => ({
          key: event.code,
          version: event.version,
          label: event.family === "DIVERGENCE" ? undefined : backtestSignalShortLabel(event.code),
          glyph: event.family === "DIVERGENCE" ? divergenceGlyphKind(event) : undefined,
          color: event.family === "DIVERGENCE"
            ? (event.version === "1.0" ? V1_DIVERGENCE_COLOR : V2_DIVERGENCE_COLOR)
            : (event.direction === "BUY" ? "#42be65" : "#fa4d56"),
        }));
        const rowHeight = 24;
        const stackHeight = items.length * rowHeight;
        const unclampedY = first.direction === "BUY" ? anchorY + 10 : anchorY - 10 - stackHeight;
        const y = Math.max(4, Math.min(chartHost.clientHeight - 90 - stackHeight, unclampedY));
        return [{
          key,
          items,
          x,
          y,
        }];
      });
      setSignalOverlays(overlays);
    };
    const scheduleUpdate = () => {
      cancelAnimationFrame(animationFrame);
      animationFrame = requestAnimationFrame(update);
    };
    const resize = new ResizeObserver(scheduleUpdate);
    resize.observe(chartHost);
    instance.timeScale().subscribeVisibleLogicalRangeChange(scheduleUpdate);
    scheduleUpdate();
    return () => {
      cancelAnimationFrame(animationFrame);
      resize.disconnect();
      instance.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleUpdate);
    };
  }, [barMap, visibleChartEvents]);

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
            ? hoverEvents.map((event) => `${backtestSignalLabel(event.code)}（信号 ${event.signal_date} · 可交易 ${event.tradable_on ?? "待下一根 K 线"}）`).join("；")
            : "移动十字线查看当日信号"}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-zinc-800 px-4 py-1.5 text-xs text-zinc-400" aria-label="统一背离信号图形说明">
        <span
          className="items-center gap-1.5"
          aria-label="统一背离：笑脸和哭脸表示一级，细箭头表示二级，宽箭头表示三级"
          style={{ display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}
        >
          背离：<DivergenceIcon kind="happy" version="1.0" size={18} /><DivergenceIcon kind="sad" version="1.0" size={18} />一级
          <DivergenceIcon kind="thin-up" version="1.0" size={18} /><DivergenceIcon kind="thin-down" version="1.0" size={18} />二级
          <DivergenceIcon kind="wide-up" version="1.0" size={18} /><DivergenceIcon kind="wide-down" version="1.0" size={18} />三级
        </span>
      </div>
      <div className="relative">
        <div ref={host} className="w-full" role="img" aria-label="回测数据 K 线、成交量与信号预览" />
        <div
          className="pointer-events-none absolute inset-0 overflow-hidden"
          aria-hidden="true"
          style={{ zIndex: 3 }}
        >
          {signalOverlays.map((marker) => (
            <span
              className="absolute -translate-x-1/2 items-center drop-shadow-[0_1px_1px_rgba(0,0,0,0.9)]"
              key={marker.key}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 2,
                left: marker.x,
                top: marker.y,
              }}
            >
              {marker.items.map((item) => (
                <span
                  key={item.key}
                  style={{
                    alignItems: "center",
                    color: item.color,
                    display: "flex",
                    fontSize: 12,
                    fontWeight: 700,
                    height: 22,
                    justifyContent: "center",
                    lineHeight: "22px",
                    whiteSpace: "nowrap",
                  }}
                >
                  {item.glyph
                    ? <DivergenceIcon kind={item.glyph} version={item.version} />
                    : item.label}
                </span>
              ))}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
