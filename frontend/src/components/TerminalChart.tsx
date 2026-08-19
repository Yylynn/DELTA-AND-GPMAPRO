import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, HistogramSeries, LineSeries, LineStyle, createChart } from "lightweight-charts";
import { Layers3, Type } from "lucide-react";

export type ChartLayer = "delta" | "gpmapro" | "all";
export type ChartBar = { time: string; open: number; high: number; low: number; close: number; volume: number };
export type DeltaWindow = { event_id: string; event_type: "HIGH" | "LOW"; actual_date: string; confirmed_on?: string | null; tradable_on?: string | null; confirmed?: boolean };
export type DeltaAnalysis = {
  timeframe?: "1d" | "1w" | "1mo";
  grid_lines?: Array<{ id: string; display_date: string; calendar_date: string; color: "ORANGE" | "GREEN" | "RED" | "BLUE" }>;
  cycle_boundaries?: Array<{ id: string; date: string; label: string }>;
  points?: Array<{ id: string; number: number; type: "HIGH" | "LOW"; date: string; display_date?: string; price: number; confirmed?: boolean }>;
  min_gap_trading_days?: number;
  future_predictions?: Array<{ id: string; number: number; type: "HIGH" | "LOW"; expected_date: string; lo_date: string; hi_date: string; gap_mean_days: number; gap_std_days: number; sample_count: number; anchor_date?: string; min_gap_earliest_date?: string; constraint_applied?: boolean; candidate_window_rebased?: boolean }>;
  boundary_point?: { id: string; number: number; type: "HIGH" | "LOW"; date: string; display_date?: string; price: number };
  transition_table?: Array<{ number: number; sample_count: number; mean_days: number | null; std_days: number | null; last_interval_days: number | null; prediction?: { expected_date: string; lo_date: string; hi_date: string; constraint_applied?: boolean; candidate_window_rebased?: boolean } | null }>;
};
type DeltaOverlay = { id: string; kind: "phase" | "boundary" | "point" | "forecast"; x: number; y?: number; label: string; color: string; dashed?: boolean; labelOffsetY?: number; detail?: string };
const DELTA_COLOURS = { ORANGE: "#e68512", GREEN: "#16a34a", RED: "#ef4444", BLUE: "#2563eb" } as const;

type EmaKey = "ema_8" | "ema_10" | "ema_12" | "ema_15" | "ema_20" | "ema_40" | "ema_45" | "ema_50" | "ema_55" | "ema_60";
type EmaColourKey = `${EmaKey}_red`;
export type GpmaDrawNode = { kind: "text" | "icon"; formula: "DRAWTEXT" | "DRAWICON"; price: number; text?: string; icon_id?: number; level?: number; direction?: "top" | "bottom" };

export type GpmaSeries = {
  time: string; close?: number; atr_26: number; ma_120: number; ma_250: number;
  b1: boolean; b2: boolean; b3: boolean; s1: boolean; s2: boolean;
  top_1: boolean; top_2: boolean; top_3: boolean; bottom_1: boolean; bottom_2: boolean; bottom_3: boolean;
  top_face: boolean; bottom_face: boolean;
  draw_nodes?: GpmaDrawNode[];
} & Record<EmaKey, number> & Record<EmaColourKey, boolean>;

type OverlayKind = "buy" | "sell" | "top-face" | "bottom-face" | "top-arrow-2" | "bottom-arrow-2" | "top-arrow-3" | "bottom-arrow-3";
type OverlaySpec = { id: string; time: string; value: number; text: string; kind: OverlayKind };
type OverlayPosition = OverlaySpec & { x: number; y: number; compact: boolean };

const EMA_LINES: Array<{ key: EmaKey; colour: EmaColourKey }> = [
  { key: "ema_8", colour: "ema_8_red" }, { key: "ema_10", colour: "ema_10_red" },
  { key: "ema_12", colour: "ema_12_red" }, { key: "ema_15", colour: "ema_15_red" },
  { key: "ema_20", colour: "ema_20_red" }, { key: "ema_40", colour: "ema_40_red" },
  { key: "ema_45", colour: "ema_45_red" }, { key: "ema_50", colour: "ema_50_red" },
  { key: "ema_55", colour: "ema_55_red" }, { key: "ema_60", colour: "ema_60_red" },
];

function isFiniteChartValue(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function chronologicalUnique<T extends { time: string }>(rows: T[]): T[] {
  const byTime = new Map<string, T>();
  rows.forEach((row) => { if (typeof row.time === "string" && row.time) byTime.set(row.time, row); });
  return [...byTime.values()].sort((left, right) => left.time.localeCompare(right.time));
}

function Annotation({ item }: { item: OverlayPosition }) {
  const scale = item.compact ? .75 : 1;
  if (item.kind === "buy" || item.kind === "sell") {
    return <text data-chart-annotation="bs" x={item.x} y={item.y} textAnchor="middle" dominantBaseline="central" fill="#1677ff" fontFamily="Arial, sans-serif" fontSize={15 * scale} fontWeight="600">{item.text}</text>;
  }
  if (item.kind === "top-face" || item.kind === "bottom-face") {
    const top = item.kind === "top-face";
    const radius = 12 * scale;
    return <g data-chart-annotation={item.kind} aria-label={top ? "顶部一级背离" : "底部一级背离"}><circle cx={item.x} cy={item.y} r={radius} fill={top ? "#b38cff" : "#ffbf2f"} stroke={top ? "#7f56d9" : "#e99b00"} /><circle cx={item.x - 4 * scale} cy={item.y - 2 * scale} r={1.25 * scale} fill={top ? "#4c1d95" : "#7a4b00"} /><circle cx={item.x + 4 * scale} cy={item.y - 2 * scale} r={1.25 * scale} fill={top ? "#4c1d95" : "#7a4b00"} /><path d={top ? `M ${item.x - 6 * scale} ${item.y + 6 * scale} Q ${item.x} ${item.y + 1 * scale} ${item.x + 6 * scale} ${item.y + 6 * scale}` : `M ${item.x - 6 * scale} ${item.y + 3 * scale} Q ${item.x} ${item.y + 8 * scale} ${item.x + 6 * scale} ${item.y + 3 * scale}`} fill="none" stroke={top ? "#4c1d95" : "#7a4b00"} strokeWidth={1.8 * scale} strokeLinecap="round" /></g>;
  }
  const top = item.kind.startsWith("top");
  const primary = item.kind.endsWith("-2");
  const size = (primary ? 10 : 8) * scale;
  const points = top ? `${item.x - size},${item.y - size} ${item.x + size},${item.y - size} ${item.x},${item.y + size}` : `${item.x - size},${item.y + size} ${item.x + size},${item.y + size} ${item.x},${item.y - size}`;
  return <polygon data-chart-annotation={item.kind} aria-label={top ? "顶部背离箭头" : "底部背离箭头"} points={points} fill={top ? "#ff9f0a" : "#26a641"} stroke={top ? "#e56b00" : "#16803a"} strokeWidth={primary ? 1.5 : 1} />;
}

export function TerminalChart({ bars, deltaWindows = [], deltaAnalysis, gpma = [], layer = "all" }: { bars: ChartBar[]; deltaWindows?: DeltaWindow[]; deltaAnalysis?: DeltaAnalysis; gpma?: GpmaSeries[]; layer?: ChartLayer }) {
  const host = useRef<HTMLDivElement>(null);
  const [selectedLayer, setSelectedLayer] = useState<ChartLayer>(layer);
  const [overlays, setOverlays] = useState<OverlayPosition[]>([]);
  const [deltaOverlays, setDeltaOverlays] = useState<DeltaOverlay[]>([]);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    if (!host.current || !bars.length) {
      // React Query briefly has no bars while a new timeframe is resolving.
      // Do not leave SVG formula annotations from the previous chart visible.
      setOverlays([]); setDeltaOverlays([]);
      return;
    }
    const chartBars = chronologicalUnique(bars.filter((bar) => [bar.open, bar.high, bar.low, bar.close, bar.volume].every(isFiniteChartValue) && bar.high >= bar.low));
    const chartGpma = chronologicalUnique(gpma);
    if (!chartBars.length) { setOverlays([]); setDeltaOverlays([]); setChartError("该股票没有可绘制的行情数据"); return; }
    setChartError(null);
    let chart: ReturnType<typeof createChart> | undefined;
    try {
    chart = createChart(host.current, {
      width: host.current.clientWidth, height: 560,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#525252" },
      grid: { vertLines: { color: "#eef0f2" }, horzLines: { color: "#eef0f2" } },
      rightPriceScale: { borderColor: "#d0d4d8" }, timeScale: { borderColor: "#d0d4d8" },
      crosshair: { vertLine: { color: "#94a3b8", labelBackgroundColor: "#334155" }, horzLine: { color: "#94a3b8", labelBackgroundColor: "#334155" } },
    });
    const activeChart = chart;
    const candles = activeChart.addSeries(CandlestickSeries, {
      // Keep candle bodies visually distinct when the ten EMA lines converge.
      upColor: "#fb3f5c", downColor: "#00aa73", wickUpColor: "#fb3f5c", wickDownColor: "#00aa73",
      borderVisible: true, borderUpColor: "#d92746", borderDownColor: "#00845a",
    });
    candles.setData(chartBars);
    candles.priceScale().applyOptions({ scaleMargins: { top: .07, bottom: .18 } });
    const volume = activeChart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "" });
    volume.setData(chartBars.map((bar) => ({ time: bar.time, value: bar.volume, color: bar.close >= bar.open ? "#fb3f5c77" : "#00aa7377" })));
    volume.priceScale().applyOptions({ scaleMargins: { top: .84, bottom: 0 } });

    if (selectedLayer !== "delta") {
      EMA_LINES.forEach(({ key, colour }) => {
        let active: Array<{ time: string; value: number }> = [];
        let activeColour: boolean | null = null;
        const flush = () => {
          if (!active.length || activeColour == null) return;
          const line = activeChart.addSeries(LineSeries, { color: activeColour ? "#f04462" : "#00a878", lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
          line.setData(active); active = [];
        };
        chartGpma.forEach((row) => {
          const value = row[key];
          // Futu emits DRAWNULL during the MA warm-up.  lightweight-charts
          // rejects null values, so make it a genuine visual line break.
          if (!isFiniteChartValue(value)) { flush(); activeColour = null; return; }
          const red = row[colour];
          if (activeColour !== null && activeColour !== red) flush();
          activeColour = red; active.push({ time: row.time, value });
        });
        flush();
      });
      const addMovingAverage = (key: "ma_120" | "ma_250", color: string) => {
        const line = activeChart.addSeries(LineSeries, { color, lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        line.setData(chartGpma.filter((row) => isFiniteChartValue(row[key])).map((row) => ({ time: row.time, value: row[key] as number })));
      };
      addMovingAverage("ma_120", "#111827");
      addMovingAverage("ma_250", "#111827");
    }
    const specs: OverlaySpec[] = [];
    if (selectedLayer !== "delta") {
      chartGpma.forEach((row) => {
        (row.draw_nodes ?? []).forEach((node, index) => {
          const kind: OverlayKind = node.kind === "text" ? (node.text?.startsWith("S") ? "sell" : "buy") : node.icon_id === 6 ? "top-face" : node.icon_id === 5 ? "bottom-face" : node.icon_id === 2 ? "top-arrow-2" : node.icon_id === 1 ? "bottom-arrow-2" : node.icon_id === 26 ? "top-arrow-3" : "bottom-arrow-3";
          specs.push({ id: `${row.time}-${index}-${node.icon_id ?? node.text}`, time: row.time, value: node.price, text: node.text ?? "", kind });
        });
      });
    }
    // This invisible series makes ATR-positioned formula annotations part of
    // the price scale.  Without it, valid face/arrow coordinates can be
    // clipped even though the backend calculated them correctly.
    if (specs.length) {
      const extents = new Map<string, { low: number; high: number }>();
      specs.forEach(({ time, value }) => {
        const previous = extents.get(time);
        extents.set(time, previous ? { low: Math.min(previous.low, value), high: Math.max(previous.high, value) } : { low: value, high: value });
      });
      const scaleOptions = { color: "transparent", lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false } as const;
      const annotationTop = activeChart.addSeries(LineSeries, scaleOptions);
      const annotationBottom = activeChart.addSeries(LineSeries, scaleOptions);
      annotationTop.setData([...extents].map(([time, value]) => ({ time, value: value.high })));
      annotationBottom.setData([...extents].map(([time, value]) => ({ time, value: value.low })));
    }
    let refreshFrame: number | undefined;
    const refreshOverlays = () => {
      if (selectedLayer === "delta") { setOverlays([]); } else {
      const first = chartBars[0] ? activeChart.timeScale().timeToCoordinate(chartBars[0].time) : null;
      const second = chartBars[1] ? activeChart.timeScale().timeToCoordinate(chartBars[1].time) : null;
      const compact = first != null && second != null && Math.abs(second - first) < 13;
      const visible = specs.flatMap((item) => {
        const x = activeChart.timeScale().timeToCoordinate(item.time); const y = candles.priceToCoordinate(item.value);
        if (x == null || y == null || x < -32 || x > (host.current?.clientWidth ?? 0) + 32 || y < -28 || y > 588) return [];
        return [{ ...item, x, y, compact }];
      });
      setOverlays(visible);
      }
      if (selectedLayer === "gpmapro") { setDeltaOverlays([]); return; }
      const width = host.current?.clientWidth ?? 0;
      const inside = (x: number | null) => x != null && x >= -20 && x <= width + 20;
      const result: DeltaOverlay[] = [];
      const displayTimeframe = deltaAnalysis?.timeframe ?? "1d";
      const phaseSpacing = displayTimeframe === "1mo" ? 72 : displayTimeframe === "1w" ? 42 : 18;
      const labelSpacing = displayTimeframe === "1mo" ? 130 : displayTimeframe === "1w" ? 94 : 58;
      let lastPhaseX = -Infinity;
      let lastLabelX = -Infinity;
      (deltaAnalysis?.grid_lines ?? []).forEach((line) => {
        const x = activeChart.timeScale().timeToCoordinate(line.display_date); if (!inside(x)) return;
        if (x! - lastPhaseX < phaseSpacing) return;
        lastPhaseX = x!;
        const labelled = x! - lastLabelX >= labelSpacing; if (labelled) lastLabelX = x!;
        result.push({ id: line.id, kind: "phase", x: x!, label: labelled ? line.calendar_date : "", color: DELTA_COLOURS[line.color], dashed: line.color !== "ORANGE" });
      });
      const boundaryId = deltaAnalysis?.boundary_point?.id;
      const labelLanes = new Map<string, number>();
      (deltaAnalysis?.points ?? []).filter((point) => point.id !== boundaryId).forEach((point) => {
        const displayDate = point.display_date ?? point.date;
        const x = activeChart.timeScale().timeToCoordinate(displayDate), y = candles.priceToCoordinate(point.price);
        if (!inside(x) || y == null) return;
        const laneKey = `${displayDate}-${point.type}`;
        const lane = labelLanes.get(laneKey) ?? 0;
        labelLanes.set(laneKey, lane + 1);
        result.push({ id: point.id, kind: "point", x: x!, y, label: String(point.number), color: point.type === "HIGH" ? "#dc2626" : "#159947", labelOffsetY: (point.type === "HIGH" ? -9 : 15) + lane * (point.type === "HIGH" ? -12 : 12) });
      });
      const boundary = deltaAnalysis?.boundary_point;
      if (boundary) {
        const x = activeChart.timeScale().timeToCoordinate(boundary.display_date ?? boundary.date), y = candles.priceToCoordinate(boundary.price);
        if (inside(x) && y != null) result.push({ id: boundary.id, kind: "forecast", x: x!, y, label: `${boundary.number}?`, color: "#c78500" });
      }
      setDeltaOverlays(result);
    };
    const scheduleOverlayRefresh = () => {
      if (refreshFrame !== undefined) window.cancelAnimationFrame(refreshFrame);
      refreshFrame = window.requestAnimationFrame(refreshOverlays);
    };
    // All history remains available through the native chart scroll/zoom, but
    // a compact latest window keeps candle bodies, B/S text and divergence
    // icons legible on first load instead of compressing them into hairlines.
    const defaultBarTarget = deltaAnalysis?.timeframe === "1mo" ? 48 : deltaAnalysis?.timeframe === "1w" ? 104 : 250;
    const defaultVisibleBars = Math.min(defaultBarTarget, chartBars.length);
    activeChart.timeScale().setVisibleLogicalRange({ from: Math.max(0, chartBars.length - defaultVisibleBars), to: chartBars.length + 8 });
    // Lightweight Charts applies its price scale after setData/range changes.
    // Schedule coordinate conversion for that completed layout, otherwise a
    // valid formula node can be filtered as y=null on the first render.
    scheduleOverlayRefresh(); activeChart.timeScale().subscribeVisibleTimeRangeChange(scheduleOverlayRefresh);
    const observer = new ResizeObserver(() => { activeChart.applyOptions({ width: host.current?.clientWidth ?? 720 }); scheduleOverlayRefresh(); });
    observer.observe(host.current);
    return () => { if (refreshFrame !== undefined) window.cancelAnimationFrame(refreshFrame); activeChart.timeScale().unsubscribeVisibleTimeRangeChange(scheduleOverlayRefresh); observer.disconnect(); activeChart.remove(); };
    } catch (error) {
      console.error("TerminalChart failed to render", error);
      chart?.remove();
      setOverlays([]); setChartError("该股票图表加载失败，请切换后重试");
    }
  }, [bars, deltaWindows, deltaAnalysis, gpma, selectedLayer]);

  const modes: Array<[ChartLayer, string]> = [["gpmapro", "GPMAPRO 主图"], ["all", "叠加 DELTA"], ["delta", "仅 DELTA"]];
  return <section className="overflow-hidden border border-slate-200 bg-white shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
      <div className="flex items-center gap-2 text-xs text-slate-500"><Layers3 size={15} strokeWidth={1.6} className="text-cyan-700" /><span className="font-medium text-slate-900">富途 GPMAPRO 主图</span><span className="hidden text-slate-400 xl:inline">K 线、EMA、E120/E250、B/S 与背离预警</span></div>
      <div className="flex shrink-0 border border-slate-300 bg-white text-xs">{modes.map(([value, label]) => <button key={value} onClick={() => setSelectedLayer(value)} className={selectedLayer === value ? "bg-cyan-500 px-3 py-1.5 font-semibold text-slate-950" : "px-3 py-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-950"}>{label}</button>)}</div>
    </div>
    <div className="relative"><div ref={host} className="h-[560px] w-full bg-white" />{chartError && <div className="absolute inset-0 grid place-items-center bg-white/95 text-sm text-rose-600">{chartError}</div>}<svg className="pointer-events-none absolute inset-0 z-10 h-[560px] w-full overflow-visible" aria-label="GPMAPRO 与 DELTA 图层">{overlays.map((item) => <Annotation key={item.id} item={item} />)}{deltaOverlays.map((item) => item.kind === "phase" || item.kind === "boundary" ? <g key={item.id}><line x1={item.x} x2={item.x} y1="0" y2="560" stroke={item.color} strokeWidth={item.kind === "boundary" ? 1.4 : 1.2} strokeDasharray={item.dashed ? "4 5" : undefined} opacity=".9" />{item.label && <text transform={`translate(${item.x - 4} 45) rotate(-32)`} fill={item.color} fontSize="10">{item.label}</text>}</g> : item.kind === "point" ? <text key={item.id} x={item.x} y={(item.y ?? 0) + (item.labelOffsetY ?? (item.color === "#dc2626" ? -9 : 15))} textAnchor="middle" fill={item.color} fontSize="12" fontWeight="700">{item.label}</text> : <g key={item.id}><circle cx={item.x} cy={item.y} r="14" fill="#fffdf6" stroke={item.color} strokeWidth="2"/><text x={item.x} y={(item.y ?? 0) + 4} textAnchor="middle" fill={item.color} fontSize="12" fontWeight="700">{item.label}</text></g>)}</svg></div>
    <div className="grid gap-x-5 gap-y-2 border-t border-slate-200 px-5 py-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-4">
      <span className="text-rose-600">红色：EMA 当前强于比较均线</span><span className="text-emerald-700">绿色：EMA 当前弱于比较均线</span><span>虚线：E120 / E250</span>
      {selectedLayer !== "delta" && <><span className="inline-flex items-center gap-1"><Type size={14} />B1–B3 / S1–S2</span><span>黄色笑脸：底部一级背离</span><span>紫色哭脸：顶部一级背离</span><span>绿色 / 橙色箭头：二、三级背离</span></>}
    </div>
    {selectedLayer !== "gpmapro" && (deltaAnalysis?.transition_table ?? []).length > 0 && <DeltaTransitionTable rows={deltaAnalysis!.transition_table!} activeNumbers={(deltaAnalysis?.future_predictions ?? []).slice(0, 2).map((item) => item.number)} minGapTradingDays={deltaAnalysis?.min_gap_trading_days ?? 8} />}
  </section>;
}

function DeltaTransitionTable({ rows, activeNumbers, minGapTradingDays }: { rows: NonNullable<DeltaAnalysis["transition_table"]>; activeNumbers: number[]; minGapTradingDays: number }) {
  const formatDays = (value: number | null, prefix = "") => value == null ? "—" : `${prefix}${value.toFixed(1)}`;
  return <div className="border-t border-zinc-700 bg-[#1b1b1b] px-5 py-5">
    <div className="mb-4 grid gap-2 border-b border-zinc-700 pb-4"><h3 className="text-base font-semibold tracking-tight text-zinc-100">DELTA 编号转移与下次出现预测</h3><p className="max-w-5xl text-xs leading-5 text-zinc-400">日期按该股票历史转移间隔均值 ± 1σ 链式推演。相邻编号至少 {minGapTradingDays} 个交易日；† 表示下限后移，‡ 表示当前候选已按实际边界更新。</p></div>
    <div className="overflow-x-auto"><table className="min-w-[820px] w-full border-collapse text-center text-xs text-zinc-300"><thead className="bg-[#242424] text-zinc-300"><tr><th className="border border-zinc-700 px-3 py-2">目标数字</th><th className="border border-zinc-700 px-3 py-2">样本数 n</th><th className="border border-zinc-700 px-3 py-2">平均间隔(天)</th><th className="border border-zinc-700 px-3 py-2">±1σ</th><th className="border border-zinc-700 px-3 py-2">最近一次(天)</th><th className="border border-zinc-700 px-3 py-2">预测下次出现（日期范围）</th></tr></thead><tbody>{rows.map((row) => { const active = activeNumbers.includes(row.number); const prediction = row.prediction; return <tr key={row.number} className={active ? "bg-[#40391f] text-[#f2e7bd]" : "bg-zinc-900"}><td className={`border border-zinc-800 px-3 py-2 font-semibold ${active ? "text-amber-200" : ""}`}>{row.number}{active && row.number === activeNumbers[0] ? "?" : ""}</td><td className="border border-zinc-800 px-3 py-2">{row.sample_count}</td><td className="border border-zinc-800 px-3 py-2">{formatDays(row.mean_days)}</td><td className="border border-zinc-800 px-3 py-2">{formatDays(row.std_days, "±")}</td><td className="border border-zinc-800 px-3 py-2">{formatDays(row.last_interval_days)}</td><td className={`border border-zinc-800 px-3 py-2 font-semibold ${active ? "text-[#f5b7b8]" : "text-rose-300"}`}>{prediction ? <>{prediction.lo_date} ～ {prediction.hi_date}{prediction.constraint_applied ? " †" : ""}{prediction.candidate_window_rebased ? " ‡" : ""}</> : "—"}</td></tr>; })}</tbody></table></div>
  </div>;
}
