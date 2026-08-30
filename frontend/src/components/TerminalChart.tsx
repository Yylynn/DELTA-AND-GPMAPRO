import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts";
import { Expand, Layers3, Shrink, Type } from "lucide-react";

export type ChartLayer = "delta" | "gpmapro" | "gpma2";
export type ChartBar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};
export type DeltaWindow = {
  event_id: string;
  event_type: "HIGH" | "LOW";
  actual_date: string;
  confirmed_on?: string | null;
  tradable_on?: string | null;
  confirmed?: boolean;
};
export type DeltaAnalysis = {
  status?: string;
  timeframe?: "1d" | "1w" | "1mo";
  grid_lines?: Array<{
    id: string;
    display_date: string;
    calendar_date: string;
    color: "ORANGE" | "GREEN" | "RED" | "BLUE";
  }>;
  cycle_boundaries?: Array<{ id: string; date: string; label: string }>;
  points?: Array<{
    id: string;
    number: number;
    type: "HIGH" | "LOW";
    date: string;
    display_date?: string;
    price: number;
    confirmed?: boolean;
  }>;
  min_gap_trading_days?: number;
  future_predictions?: Array<{
    id: string;
    number: number;
    type: "HIGH" | "LOW";
    expected_date: string;
    lo_date: string;
    hi_date: string;
    gap_mean_days: number;
    gap_std_days: number;
    sample_count: number;
    anchor_date?: string;
    min_gap_earliest_date?: string;
    constraint_applied?: boolean;
    candidate_window_rebased?: boolean;
    overlaps_previous_window?: boolean;
    overlap_start?: string | null;
    overlap_end?: string | null;
    previous_number?: number | null;
    requires_previous_confirmation?: boolean;
    conditional?: boolean;
    independent_window_eligible?: boolean;
  }>;
  boundary_point?: {
    id: string;
    number: number;
    type: "HIGH" | "LOW";
    date: string;
    display_date?: string;
    price: number;
  };
  transition_table?: Array<{
    number: number;
    sample_count: number;
    mean_days: number | null;
    std_days: number | null;
    last_interval_days: number | null;
    prediction?: {
      expected_date: string;
      lo_date: string;
      hi_date: string;
      constraint_applied?: boolean;
      candidate_window_rebased?: boolean;
      overlaps_previous_window?: boolean;
      overlap_start?: string | null;
      overlap_end?: string | null;
      previous_number?: number | null;
      requires_previous_confirmation?: boolean;
      conditional?: boolean;
      independent_window_eligible?: boolean;
    } | null;
  }>;
  reversal?: {
    state:
      | "NORMAL"
      | "ITW_WATCH"
      | "AI_WATCH"
      | "INVERSION_CONFIRMED"
      | "DOUBLE_INVERSION_CONFIRMED";
    itw_active: boolean;
    ai?: { available: boolean; threshold: number };
    windows?: Array<{
      id: string;
      state: string;
      display_start?: string;
      display_end?: string;
      ibp_ids: string[];
      ai_probability?: number;
    }>;
    ibps?: Array<{
      id: string;
      label: "M'" | "1'";
      type: "HIGH" | "LOW";
      price: number;
      display_date?: string;
      date: string;
      confirmed_on: string;
      tradable_on?: string | null;
      ai?: { probability: number | null };
    }>;
  };
};
type DeltaOverlay = {
  id: string;
  kind: "phase" | "boundary" | "point" | "forecast" | "ibp";
  x: number;
  y?: number;
  label: string;
  color: string;
  dashed?: boolean;
  labelOffsetY?: number;
  detail?: string;
};
const DELTA_COLOURS = {
  ORANGE: "#e68512",
  GREEN: "#16a34a",
  RED: "#ef4444",
  BLUE: "#2563eb",
} as const;

type EmaKey =
  | "ema_8"
  | "ema_10"
  | "ema_12"
  | "ema_15"
  | "ema_20"
  | "ema_40"
  | "ema_45"
  | "ema_50"
  | "ema_55"
  | "ema_60";
type EmaColourKey = `${EmaKey}_red`;
type OverlayKind =
  | "buy"
  | "sell"
  | "top-face"
  | "bottom-face"
  | "top-arrow-2"
  | "bottom-arrow-2"
  | "top-arrow-3"
  | "bottom-arrow-3";
export type GpmaDrawNode = {
  kind: "text" | "icon";
  formula: "DRAWTEXT" | "DRAWICON";
  price: number;
  text?: string;
  icon_id?: number;
  visual?: Exclude<OverlayKind, "buy" | "sell">;
  level?: number;
  direction?: "top" | "bottom";
};

export type GpmaSeries = {
  time: string;
  close?: number;
  atr_26: number;
  ma_120: number;
  ma_250: number;
  b1: boolean;
  b2: boolean;
  b3: boolean;
  s1: boolean;
  s2: boolean;
  top_1: boolean;
  top_2: boolean;
  top_3: boolean;
  bottom_1: boolean;
  bottom_2: boolean;
  bottom_3: boolean;
  top_face: boolean;
  bottom_face: boolean;
  draw_nodes?: GpmaDrawNode[];
} & Record<EmaKey, number> &
  Record<EmaColourKey, boolean>;

type OverlaySpec = {
  id: string;
  time: string;
  value: number;
  text: string;
  kind: OverlayKind;
};
type OverlayPosition = OverlaySpec & {
  x: number;
  y: number;
  compact: boolean;
  detail?: string;
};
type AnnotationSide = "top" | "bottom";
type LayoutItem = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  side: AnnotationSide;
  priority: number;
};

const EMA_LINES: Array<{ key: EmaKey; colour: EmaColourKey }> = [
  { key: "ema_8", colour: "ema_8_red" },
  { key: "ema_10", colour: "ema_10_red" },
  { key: "ema_12", colour: "ema_12_red" },
  { key: "ema_15", colour: "ema_15_red" },
  { key: "ema_20", colour: "ema_20_red" },
  { key: "ema_40", colour: "ema_40_red" },
  { key: "ema_45", colour: "ema_45_red" },
  { key: "ema_50", colour: "ema_50_red" },
  { key: "ema_55", colour: "ema_55_red" },
  { key: "ema_60", colour: "ema_60_red" },
];

function isFiniteChartValue(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function colorWithAlpha(hex: string, alpha: number) {
  const normalized = hex.replace("#", "");
  const value = Number.parseInt(normalized, 16);
  return `rgba(${value >> 16}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

function chronologicalUnique<T extends { time: string }>(rows: T[]): T[] {
  const byTime = new Map<string, T>();
  rows.forEach((row) => {
    if (typeof row.time === "string" && row.time) byTime.set(row.time, row);
  });
  return [...byTime.values()].sort((left, right) =>
    left.time.localeCompare(right.time),
  );
}

function overlaps(left: LayoutItem, right: LayoutItem) {
  return (
    Math.abs(left.x - right.x) < (left.width + right.width) / 2 + 3 &&
    Math.abs(left.y - right.y) < (left.height + right.height) / 2 + 3
  );
}

/** Place chart labels in outward-facing tracks without changing price anchors. */
function arrangeAnnotations<T extends LayoutItem>(
  items: T[],
  reserved: LayoutItem[] = [],
  height = 560,
): T[] {
  const occupied = [...reserved];
  const horizontalOffsets = [0, -7, 7, -14, 14, -21, 21];
  const arranged: T[] = [];
  [...items]
    .sort((a, b) => b.priority - a.priority)
    .forEach((item) => {
      let chosen: T | undefined;
      for (let lane = 0; lane < 9 && !chosen; lane += 1) {
        for (const offset of horizontalOffsets) {
          const candidate = {
            ...item,
            x: item.x + offset,
            y: item.y + (item.side === "top" ? -lane * 20 : lane * 20),
          };
          if (
            candidate.y - candidate.height / 2 < 16 ||
            candidate.y + candidate.height / 2 > height - 18
          )
            continue;
          if (!occupied.some((other) => overlaps(candidate, other))) {
            chosen = candidate;
            break;
          }
        }
      }
      // The available tracks cover the visible price area; retain a final
      // outward location instead of silently losing an exceptional dense label.
      const placed = chosen ?? {
        ...item,
        y: Math.max(
          18 + item.height / 2,
          Math.min(
            height - 18 - item.height / 2,
            item.y + (item.side === "top" ? -180 : 180),
          ),
        ),
      };
      occupied.push(placed);
      arranged.push(placed);
    });
  return arranged;
}

function overlaySide(item: Pick<OverlayPosition, "kind">): AnnotationSide {
  return item.kind === "sell" || item.kind.startsWith("top") ? "top" : "bottom";
}

function overlayLayoutItem(item: OverlayPosition): LayoutItem {
  const scale = item.compact ? 0.75 : 1;
  const face = item.kind === "top-face" || item.kind === "bottom-face";
  const arrow =
    item.kind.startsWith("top-arrow") || item.kind.startsWith("bottom-arrow");
  const width = face
    ? 27 * scale
    : arrow
      ? 23 * scale
      : Math.max(18, item.text.length * 9 * scale);
  const priority = face ? 100 : arrow ? 80 : 70;
  return {
    id: item.id,
    x: item.x,
    y: item.y,
    width,
    height: face ? 27 * scale : arrow ? 23 * scale : 17 * scale,
    side: overlaySide(item),
    priority,
  };
}

function foldDenseGpmaText(items: OverlayPosition[]): OverlayPosition[] {
  const result: OverlayPosition[] = [];
  const consumed = new Set<string>();
  items.forEach((item, index) => {
    if (
      consumed.has(item.id) ||
      (item.kind !== "buy" && item.kind !== "sell")
    ) {
      if (!consumed.has(item.id)) result.push(item);
      return;
    }
    const side = overlaySide(item);
    const cluster = items
      .slice(index)
      .filter(
        (candidate) =>
          !consumed.has(candidate.id) &&
          candidate.kind === item.kind &&
          overlaySide(candidate) === side &&
          Math.abs(candidate.x - item.x) < 14 &&
          Math.abs(candidate.y - item.y) < 18,
      );
    cluster.forEach((candidate) => consumed.add(candidate.id));
    result.push(
      cluster.length === 1
        ? item
        : {
            ...item,
            id: `${item.id}-cluster`,
            text: `+${cluster.length}`,
            detail: cluster.map((candidate) => candidate.text).join(" · "),
          },
    );
  });
  return result;
}

function Annotation({ item }: { item: OverlayPosition }) {
  const scale = item.compact ? 0.75 : 1;
  if (item.kind === "buy" || item.kind === "sell") {
    return (
      <g
        data-chart-annotation="bs"
        aria-label={item.detail ?? item.text}
        pointerEvents={item.detail ? "auto" : "none"}
        cursor={item.detail ? "help" : undefined}
      >
        <title>{item.detail ?? item.text}</title>
        <text
          x={item.x}
          y={item.y}
          textAnchor="middle"
          dominantBaseline="central"
          fill="#1677ff"
          fontFamily="Arial, sans-serif"
          fontSize={15 * scale}
          fontWeight="600"
        >
          {item.text}
        </text>
      </g>
    );
  }
  if (item.kind === "top-face" || item.kind === "bottom-face") {
    const top = item.kind === "top-face";
    const radius = 12 * scale;
    const faceStroke = "#9a6500";
    return (
      <g
        data-chart-annotation={item.kind}
        aria-label={top ? "顶部一级背离哭脸" : "底部一级背离笑脸"}
      >
        <circle
          cx={item.x}
          cy={item.y}
          r={radius}
          fill="#ffd34f"
          stroke="#d28a00"
          strokeWidth={1.4 * scale}
        />
        <circle
          cx={item.x - 4 * scale}
          cy={item.y - 2 * scale}
          r={1.35 * scale}
          fill={faceStroke}
        />
        <circle
          cx={item.x + 4 * scale}
          cy={item.y - 2 * scale}
          r={1.35 * scale}
          fill={faceStroke}
        />
        {top && (
          <path
            d={`M ${item.x + 5.5 * scale} ${item.y + 0.5 * scale} Q ${item.x + 9 * scale} ${item.y + 4 * scale} ${item.x + 5.5 * scale} ${item.y + 7.5 * scale} Q ${item.x + 2 * scale} ${item.y + 4 * scale} ${item.x + 5.5 * scale} ${item.y + 0.5 * scale}`}
            fill="#4da3ff"
            stroke="#1976d2"
            strokeWidth={0.65 * scale}
          />
        )}
        <path
          d={
            top
              ? `M ${item.x - 6 * scale} ${item.y + 6 * scale} Q ${item.x} ${item.y + 1 * scale} ${item.x + 6 * scale} ${item.y + 6 * scale}`
              : `M ${item.x - 6 * scale} ${item.y + 2 * scale} Q ${item.x} ${item.y + 8 * scale} ${item.x + 6 * scale} ${item.y + 2 * scale}`
          }
          fill="none"
          stroke={faceStroke}
          strokeWidth={1.8 * scale}
          strokeLinecap="round"
        />
      </g>
    );
  }
  const top = item.kind.startsWith("top");
  const primary = item.kind.endsWith("-2");
  const size = (primary ? 10 : 8) * scale;
  const points = top
    ? `${item.x - size},${item.y - size} ${item.x + size},${item.y - size} ${item.x},${item.y + size}`
    : `${item.x - size},${item.y + size} ${item.x + size},${item.y + size} ${item.x},${item.y - size}`;
  return (
    <polygon
      data-chart-annotation={item.kind}
      aria-label={top ? "顶部背离箭头" : "底部背离箭头"}
      points={points}
      fill={top ? "#ff9f0a" : "#26a641"}
      stroke={top ? "#e56b00" : "#16803a"}
      strokeWidth={primary ? 1.5 : 1}
    />
  );
}

export function TerminalChart({
  bars,
  deltaWindows = [],
  deltaAnalysis,
  gpma = [],
  gpma2 = [],
  layer = "gpmapro",
  focusDate,
  compact = false,
  mode,
  deltaAnalysisLoading = false,
  deltaAnalysisError,
}: {
  bars: ChartBar[];
  deltaWindows?: DeltaWindow[];
  deltaAnalysis?: DeltaAnalysis;
  gpma?: GpmaSeries[];
  gpma2?: GpmaSeries[];
  layer?: ChartLayer;
  focusDate?: string;
  /** Keeps the full chart interaction but uses the overview command-center height. */
  compact?: boolean;
  /** Controls chart height while keeping DELTA forecasts visible in both modes. */
  mode?: "overview" | "research";
  deltaAnalysisLoading?: boolean;
  deltaAnalysisError?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [selectedLayer, setSelectedLayer] = useState<ChartLayer>(layer);
  const [overlays, setOverlays] = useState<OverlayPosition[]>([]);
  const [deltaOverlays, setDeltaOverlays] = useState<DeltaOverlay[]>([]);
  const [chartError, setChartError] = useState<string | null>(null);
  const [isFocusOpen, setIsFocusOpen] = useState(false);
  const [viewportHeight, setViewportHeight] = useState(() =>
    typeof window === "undefined" ? 900 : window.innerHeight,
  );
  const chartMode = mode ?? (compact ? "overview" : "research");
  const chartHeight = isFocusOpen
    ? Math.max(420, viewportHeight - 126)
    : chartMode === "overview"
      ? 410
      : 560;

  useEffect(() => {
    if (!isFocusOpen) return;
    const previousOverflow = document.body.style.overflow;
    const onResize = () => setViewportHeight(window.innerHeight);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsFocusOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isFocusOpen]);

  useEffect(() => {
    if (!host.current || !bars.length) {
      // React Query briefly has no bars while a new timeframe is resolving.
      // Do not leave SVG formula annotations from the previous chart visible.
      setOverlays([]);
      setDeltaOverlays([]);
      return;
    }
    const chartBars = chronologicalUnique(
      bars.filter(
        (bar) =>
          [bar.open, bar.high, bar.low, bar.close, bar.volume].every(
            isFiniteChartValue,
          ) && bar.high >= bar.low,
      ),
    );
    const chartGpma = chronologicalUnique(
      selectedLayer === "gpma2" ? gpma2 : gpma,
    );
    if (!chartBars.length) {
      setOverlays([]);
      setDeltaOverlays([]);
      setChartError("该股票没有可绘制的行情数据");
      return;
    }
    setChartError(null);
    const css = getComputedStyle(document.documentElement);
    const chartTheme = {
      canvas: css.getPropertyValue("--ws-surface-1").trim(),
      surface: css.getPropertyValue("--ws-surface-2").trim(),
      border: css.getPropertyValue("--ws-border").trim(),
      grid: css.getPropertyValue("--ws-chart-grid").trim(),
      text: css.getPropertyValue("--ws-text-muted").trim(),
      primaryText: css.getPropertyValue("--ws-text-primary").trim(),
      accent: css.getPropertyValue("--ws-accent").trim(),
      success: css.getPropertyValue("--ws-success").trim(),
      danger: css.getPropertyValue("--ws-danger").trim(),
    };
    let chart: ReturnType<typeof createChart> | undefined;
    try {
      chart = createChart(host.current, {
        width: host.current.clientWidth,
        height: chartHeight,
        layout: {
          background: { type: ColorType.Solid, color: chartTheme.canvas },
          textColor: chartTheme.text,
        },
        grid: {
          vertLines: { color: chartTheme.grid },
          horzLines: { color: chartTheme.grid },
        },
        rightPriceScale: { borderColor: chartTheme.border },
        timeScale: { borderColor: chartTheme.border },
        crosshair: {
          vertLine: {
            color: chartTheme.text,
            labelBackgroundColor: chartTheme.surface,
          },
          horzLine: {
            color: chartTheme.text,
            labelBackgroundColor: chartTheme.surface,
          },
        },
      });
      const activeChart = chart;
      const candles = activeChart.addSeries(CandlestickSeries, {
        // Keep candle bodies visually distinct when the ten EMA lines converge.
        upColor: chartTheme.danger,
        downColor: chartTheme.success,
        wickUpColor: chartTheme.danger,
        wickDownColor: chartTheme.success,
        borderVisible: true,
        borderUpColor: chartTheme.danger,
        borderDownColor: chartTheme.success,
      });
      candles.setData(chartBars);
      candles
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.07, bottom: 0.18 } });
      const volume = activeChart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "",
      });
      volume.setData(
        chartBars.map((bar) => ({
          time: bar.time,
          value: bar.volume,
          color:
            bar.close >= bar.open
              ? colorWithAlpha(chartTheme.danger, 0.46)
              : colorWithAlpha(chartTheme.success, 0.46),
        })),
      );
      volume
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });

      if (selectedLayer !== "delta") {
        EMA_LINES.forEach(({ key, colour }) => {
          let active: Array<{ time: string; value: number }> = [];
          let activeColour: boolean | null = null;
          const flush = () => {
            if (!active.length || activeColour == null) return;
            const line = activeChart.addSeries(LineSeries, {
              color: activeColour ? chartTheme.danger : chartTheme.success,
              lineWidth: 1,
              lastValueVisible: false,
              priceLineVisible: false,
              crosshairMarkerVisible: false,
            });
            line.setData(active);
            active = [];
          };
          chartGpma.forEach((row) => {
            const value = row[key];
            // Futu emits DRAWNULL during the MA warm-up.  lightweight-charts
            // rejects null values, so make it a genuine visual line break.
            if (!isFiniteChartValue(value)) {
              flush();
              activeColour = null;
              return;
            }
            const red = row[colour];
            if (activeColour !== null && activeColour !== red) flush();
            activeColour = red;
            active.push({ time: row.time, value });
          });
          flush();
        });
        const addMovingAverage = (key: "ma_120" | "ma_250", color: string) => {
          const line = activeChart.addSeries(LineSeries, {
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          line.setData(
            chartGpma
              .filter((row) => isFiniteChartValue(row[key]))
              .map((row) => ({ time: row.time, value: row[key] as number })),
          );
        };
        addMovingAverage("ma_120", chartTheme.text);
        addMovingAverage("ma_250", chartTheme.text);
      }
      const specs: OverlaySpec[] = [];
      if (selectedLayer !== "delta") {
        chartGpma.forEach((row) => {
          (row.draw_nodes ?? []).forEach((node, index) => {
            // GPMA2's icon 4 means a top crying face, while old GPMAPRO uses
            // a different numbering scheme.  New sources send `visual`; the
            // fallback below is deliberately retained only for old responses.
            const kind: OverlayKind =
              node.kind === "text"
                ? node.text?.startsWith("S")
                  ? "sell"
                  : "buy"
                : (node.visual ??
                  (node.icon_id === 6
                    ? "top-face"
                    : node.icon_id === 5
                      ? "bottom-face"
                      : node.icon_id === 2
                        ? "top-arrow-2"
                        : node.icon_id === 1
                          ? "bottom-arrow-2"
                          : node.icon_id === 26
                            ? "top-arrow-3"
                            : "bottom-arrow-3"));
            specs.push({
              id: `${row.time}-${index}-${node.icon_id ?? node.text}`,
              time: row.time,
              value: node.price,
              text: node.text ?? "",
              kind,
            });
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
          extents.set(
            time,
            previous
              ? {
                  low: Math.min(previous.low, value),
                  high: Math.max(previous.high, value),
                }
              : { low: value, high: value },
          );
        });
        const scaleOptions = {
          color: "transparent",
          lineVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        } as const;
        const annotationTop = activeChart.addSeries(LineSeries, scaleOptions);
        const annotationBottom = activeChart.addSeries(
          LineSeries,
          scaleOptions,
        );
        annotationTop.setData(
          [...extents].map(([time, value]) => ({ time, value: value.high })),
        );
        annotationBottom.setData(
          [...extents].map(([time, value]) => ({ time, value: value.low })),
        );
      }
      let refreshFrame: number | undefined;
      const refreshOverlays = () => {
        let laidOutGpma: OverlayPosition[] = [];
        if (selectedLayer === "delta") {
          setOverlays([]);
        } else {
          const first = chartBars[0]
            ? activeChart.timeScale().timeToCoordinate(chartBars[0].time)
            : null;
          const second = chartBars[1]
            ? activeChart.timeScale().timeToCoordinate(chartBars[1].time)
            : null;
          const compact =
            first != null && second != null && Math.abs(second - first) < 13;
          const visible = specs.flatMap((item) => {
            const x = activeChart.timeScale().timeToCoordinate(item.time);
            const y = candles.priceToCoordinate(item.value);
            if (
              x == null ||
              y == null ||
              x < -32 ||
              x > (host.current?.clientWidth ?? 0) + 32 ||
              y < -28 ||
              y > chartHeight + 28
            )
              return [];
            return [{ ...item, x, y, compact }];
          });
          const folded = foldDenseGpmaText(visible);
          const positions = new Map(
            arrangeAnnotations(folded.map(overlayLayoutItem), [], chartHeight).map((item) => [
              item.id,
              item,
            ]),
          );
          laidOutGpma = folded.map((item) => ({
            ...item,
            x: positions.get(item.id)?.x ?? item.x,
            y: positions.get(item.id)?.y ?? item.y,
          }));
          setOverlays(laidOutGpma);
        }
        const width = host.current?.clientWidth ?? 0;
        const inside = (x: number | null) =>
          x != null && x >= -20 && x <= width + 20;
        const result: DeltaOverlay[] = [];
        const displayTimeframe = deltaAnalysis?.timeframe ?? "1d";
        const phaseSpacing =
          displayTimeframe === "1mo" ? 72 : displayTimeframe === "1w" ? 42 : 18;
        const labelSpacing =
          displayTimeframe === "1mo"
            ? 130
            : displayTimeframe === "1w"
              ? 94
              : 58;
        let lastPhaseX = -Infinity;
        let lastLabelX = -Infinity;
        (deltaAnalysis?.grid_lines ?? []).forEach((line) => {
          const x = activeChart.timeScale().timeToCoordinate(line.display_date);
          if (!inside(x)) return;
          if (x! - lastPhaseX < phaseSpacing) return;
          lastPhaseX = x!;
          const labelled = x! - lastLabelX >= labelSpacing;
          if (labelled) lastLabelX = x!;
          result.push({
            id: line.id,
            kind: "phase",
            x: x!,
            label: labelled ? line.calendar_date : "",
            color: DELTA_COLOURS[line.color],
            dashed: line.color !== "ORANGE",
          });
        });
        const boundaryId = deltaAnalysis?.boundary_point?.id;
        const labelLanes = new Map<string, number>();
        (deltaAnalysis?.points ?? [])
          .filter((point) => point.id !== boundaryId)
          .forEach((point) => {
            const displayDate = point.display_date ?? point.date;
            const x = activeChart.timeScale().timeToCoordinate(displayDate),
              y = candles.priceToCoordinate(point.price);
            if (!inside(x) || y == null) return;
            const laneKey = `${displayDate}-${point.type}`;
            const lane = labelLanes.get(laneKey) ?? 0;
            labelLanes.set(laneKey, lane + 1);
            result.push({
              id: point.id,
              kind: "point",
              x: x!,
              y,
              label: String(point.number),
              color: point.type === "HIGH" ? "#dc2626" : "#159947",
              labelOffsetY:
                (point.type === "HIGH" ? -9 : 15) +
                lane * (point.type === "HIGH" ? -12 : 12),
            });
          });
        const boundary = deltaAnalysis?.boundary_point;
        if (boundary) {
          const x = activeChart
              .timeScale()
              .timeToCoordinate(boundary.display_date ?? boundary.date),
            y = candles.priceToCoordinate(boundary.price);
          if (inside(x) && y != null)
            result.push({
              id: boundary.id,
              kind: "forecast",
              x: x!,
              y,
              label: `${boundary.number}?`,
              color: "#c78500",
            });
        }
        (deltaAnalysis?.reversal?.ibps ?? []).forEach((ibp) => {
          const x = activeChart
              .timeScale()
              .timeToCoordinate(ibp.display_date ?? ibp.date),
            y = candles.priceToCoordinate(ibp.price);
          if (inside(x) && y != null)
            result.push({
              id: ibp.id,
              kind: "ibp",
              x: x!,
              y,
              label: ibp.label,
              color: "#7c3aed",
              dashed: true,
              detail: `确认：${ibp.confirmed_on}`,
            });
        });
        const reserved = laidOutGpma.map(overlayLayoutItem);
        const deltaLabels = result.flatMap((item) => {
          if (
            item.kind !== "point" &&
            item.kind !== "forecast" &&
            item.kind !== "ibp"
          )
            return [];
          const top =
            item.kind === "point"
              ? item.color === "#dc2626"
              : (item.y ?? 0) < chartHeight / 2;
          const centerY =
            item.kind === "point"
              ? (item.y ?? 0) + (item.labelOffsetY ?? (top ? -9 : 15))
              : (item.y ?? 0);
          const circle = item.kind === "forecast" || item.kind === "ibp";
          return [
            {
              id: `delta-${item.id}`,
              x: item.x,
              y: centerY,
              width: circle ? 30 : Math.max(15, item.label.length * 8),
              height: circle ? 30 : 15,
              side: top ? ("top" as const) : ("bottom" as const),
              priority: 50,
            },
          ];
        });
        const deltaPositions = new Map(
          arrangeAnnotations(deltaLabels, reserved, chartHeight).map((item) => [
            item.id,
            item,
          ]),
        );
        setDeltaOverlays(
          result.map((item) => {
            const position = deltaPositions.get(`delta-${item.id}`);
            if (!position) return item;
            if (item.kind === "point")
              return {
                ...item,
                x: position.x,
                labelOffsetY: position.y - (item.y ?? 0),
              };
            return { ...item, x: position.x, y: position.y };
          }),
        );
      };
      const scheduleOverlayRefresh = () => {
        if (refreshFrame !== undefined)
          window.cancelAnimationFrame(refreshFrame);
        refreshFrame = window.requestAnimationFrame(refreshOverlays);
      };
      // All history remains available through the native chart scroll/zoom, but
      // a compact latest window keeps candle bodies, B/S text and divergence
      // icons legible on first load instead of compressing them into hairlines.
      const defaultBarTarget =
        deltaAnalysis?.timeframe === "1mo"
          ? 48
          : deltaAnalysis?.timeframe === "1w"
            ? 104
            : 250;
      const defaultVisibleBars = Math.min(defaultBarTarget, chartBars.length);
      const focusIndex = focusDate
        ? chartBars.findIndex((bar) => bar.time === focusDate)
        : -1;
      activeChart
        .timeScale()
        .setVisibleLogicalRange(
          focusIndex >= 0
            ? {
                from: Math.max(
                  0,
                  focusIndex - Math.floor(defaultVisibleBars / 2),
                ),
                to: Math.min(
                  chartBars.length + 8,
                  focusIndex + Math.floor(defaultVisibleBars / 2),
                ),
              }
            : {
                from: Math.max(0, chartBars.length - defaultVisibleBars),
                to: chartBars.length + 8,
              },
        );
      // Lightweight Charts applies its price scale after setData/range changes.
      // Schedule coordinate conversion for that completed layout, otherwise a
      // valid formula node can be filtered as y=null on the first render.
      scheduleOverlayRefresh();
      activeChart
        .timeScale()
        .subscribeVisibleTimeRangeChange(scheduleOverlayRefresh);
      const observer = new ResizeObserver(() => {
        activeChart.applyOptions({ width: host.current?.clientWidth ?? 720 });
        scheduleOverlayRefresh();
      });
      observer.observe(host.current);
      return () => {
        if (refreshFrame !== undefined)
          window.cancelAnimationFrame(refreshFrame);
        activeChart
          .timeScale()
          .unsubscribeVisibleTimeRangeChange(scheduleOverlayRefresh);
        observer.disconnect();
        activeChart.remove();
      };
    } catch (error) {
      console.error("TerminalChart failed to render", error);
      chart?.remove();
      setOverlays([]);
      setChartError("该股票图表加载失败，请切换后重试");
    }
  }, [
    bars,
    deltaWindows,
    deltaAnalysis,
    gpma,
    gpma2,
    selectedLayer,
    focusDate,
    chartHeight,
  ]);

  const modes: Array<[ChartLayer, string]> = [
    ["gpmapro", "GPMAPRO + DELTA"],
    ["gpma2", "GPMA2 + DELTA"],
    ["delta", "仅 DELTA"],
  ];
  return (
    <section
      className={`chart-panel${chartMode === "overview" ? " chart-panel-compact" : ""}${isFocusOpen ? " chart-panel-focus" : ""}`}
      aria-label={isFocusOpen ? "走势图专注模式" : "走势图"}
    >
      <div className="chart-toolbar">
        <div className="chart-title">
          <Layers3 size={15} strokeWidth={1.6} />
          <span>
            {selectedLayer === "gpma2"
              ? "富途 GPMA2 + DELTA"
              : selectedLayer === "delta"
                ? "DELTA 主图"
                : "富途 GPMAPRO + DELTA"}
          </span>
          <small>同一 OHLCV 快照与时间轴</small>
        </div>
        <div className="chart-toolbar-controls">
          <div className="chart-modes">
            {modes.map(([value, label]) => (
              <button
                key={value}
                onClick={() => setSelectedLayer(value)}
                className={selectedLayer === value ? "active" : ""}
              >
                {label}
              </button>
            ))}
          </div>
          {chartMode === "overview" && (
            <button
              className="chart-focus-button"
              type="button"
              onClick={() => setIsFocusOpen((open) => !open)}
              aria-label={isFocusOpen ? "退出全屏走势" : "打开全屏走势"}
              title={isFocusOpen ? "退出全屏走势（Esc）" : "全屏走势"}
            >
              {isFocusOpen ? <Shrink size={15} /> : <Expand size={15} />}
              <span>{isFocusOpen ? "退出全屏" : "全屏走势"}</span>
            </button>
          )}
        </div>
      </div>
      <div className="relative">
        <div ref={host} className="w-full" style={{ height: chartHeight }} />
        {chartError && <div className="chart-error">{chartError}</div>}
        <svg
          className="pointer-events-none absolute inset-0 z-10 w-full overflow-visible"
          style={{ height: chartHeight }}
          aria-label="GPMAPRO 与 DELTA 图层"
        >
          {overlays.map((item) => (
            <Annotation key={item.id} item={item} />
          ))}
          {deltaOverlays.map((item) =>
            item.kind === "phase" || item.kind === "boundary" ? (
              <g key={item.id}>
                <line
                  x1={item.x}
                  x2={item.x}
                  y1="0"
                  y2={chartHeight}
                  stroke={item.color}
                  strokeWidth={item.kind === "boundary" ? 1.4 : 1.2}
                  strokeDasharray={item.dashed ? "4 5" : undefined}
                  opacity=".9"
                />
                {item.label && (
                  <text
                    transform={`translate(${item.x - 4} 45) rotate(-32)`}
                    fill={item.color}
                    fontSize="10"
                  >
                    {item.label}
                  </text>
                )}
              </g>
            ) : item.kind === "point" ? (
              <text
                key={item.id}
                x={item.x}
                y={
                  (item.y ?? 0) +
                  (item.labelOffsetY ?? (item.color === "#dc2626" ? -9 : 15))
                }
                textAnchor="middle"
                fill={item.color}
                fontSize="12"
                fontWeight="700"
              >
                {item.label}
              </text>
            ) : (
              <g key={item.id}>
                <circle
                  cx={item.x}
                  cy={item.y}
                  r={item.kind === "ibp" ? "12" : "14"}
                  className="chart-forecast-node"
                  stroke={item.color}
                  strokeWidth="2"
                  strokeDasharray={item.dashed ? "4 3" : undefined}
                />
                <text
                  x={item.x}
                  y={(item.y ?? 0) + 4}
                  textAnchor="middle"
                  fill={item.color}
                  fontSize="12"
                  fontWeight="700"
                >
                  {item.label}
                </text>
              </g>
            ),
          )}
        </svg>
      </div>
      <div className="chart-legend">
        <span className="chart-legend-up">红色：EMA 当前强于比较均线</span>
        <span className="chart-legend-down">绿色：EMA 当前弱于比较均线</span>
        <span>虚线：E120 / E250</span>
        <span>标注自动避让；“+N”可悬停查看合并信号</span>
        {selectedLayer === "gpmapro" && (
          <>
            <span className="inline-flex items-center gap-1">
              <Type size={14} />
              B1–B3 / S1–S2
            </span>
            <span>黄色笑脸：底部一级背离</span>
            <span>紫色哭脸：顶部一级背离</span>
            <span>绿色 / 橙色箭头：二、三级背离</span>
          </>
        )}
        {selectedLayer === "gpma2" && (
          <>
            <span className="inline-flex items-center gap-1">
              <Type size={14} />
              B01–B4 / B11–B12 / S01–S22
            </span>
            <span>黄色哭脸 / 笑脸：一级顶 / 底背离</span>
            <span>橙色 / 绿色箭头：二级顶 / 底背离</span>
            <span>GPMA2：富途逐 bar 权威输出</span>
          </>
        )}
      </div>
      {(deltaAnalysis?.transition_table ?? []).length > 0 ? (
        <DeltaTransitionTable
          rows={deltaAnalysis!.transition_table!}
          activeNumbers={(deltaAnalysis?.future_predictions ?? [])
            .slice(0, 2)
            .map((item) => item.number)}
          minGapTradingDays={deltaAnalysis?.min_gap_trading_days ?? 8}
        />
      ) : (
        <DeltaForecastEmptyState
          loading={deltaAnalysisLoading}
          error={deltaAnalysisError}
          status={deltaAnalysis?.status}
        />
      )}
      {selectedLayer !== "gpmapro" && (
        <div className="chart-status">
          <span>ITW 倒转：{deltaAnalysis?.reversal?.state ?? "NORMAL"}</span>
          <small>虚线紫圈为 IBP；仅在确认日后生效。</small>
        </div>
      )}
    </section>
  );
}

function DeltaForecastEmptyState({
  loading,
  error,
  status,
}: {
  loading: boolean;
  error?: string;
  status?: string;
}) {
  const message = loading
    ? "正在计算当前快照的 DELTA 转移与预测日期。"
    : error
      ? `DELTA 预测暂不可用：${error}`
      : status === "INSUFFICIENT_HISTORY"
        ? "历史数据不足，至少需要 118 根有效 K 线才能生成 DELTA 预测。"
        : "当前快照尚未形成可展示的 DELTA 预测日期。";
  return (
    <section className="delta-forecast-empty" aria-live="polite">
      <h3>DELTA 编号转移与下次出现预测</h3>
      <p>{message}</p>
    </section>
  );
}

function DeltaTransitionTable({
  rows,
  activeNumbers,
  minGapTradingDays,
}: {
  rows: NonNullable<DeltaAnalysis["transition_table"]>;
  activeNumbers: number[];
  minGapTradingDays: number;
}) {
  const formatDays = (value: number | null, prefix = "") =>
    value == null ? "—" : `${prefix}${value.toFixed(1)}`;
  return (
    <div className="border-t border-zinc-700 bg-[#1b1b1b] px-5 py-5">
      <div className="mb-4 grid gap-2 border-b border-zinc-700 pb-4">
        <h3 className="text-base font-semibold tracking-tight text-zinc-100">
          DELTA 编号转移与下次出现预测
        </h3>
        <p className="max-w-5xl text-xs leading-5 text-zinc-400">
          日期按该股票历史转移间隔均值 ± 1σ 链式推演。相邻编号至少{" "}
          {minGapTradingDays} 个交易日；统计日期范围可以重叠，重叠不表示两个实际转折点同时发生。† 表示下限后移，‡
          表示当前候选已按实际边界更新。
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[820px] w-full border-collapse text-center text-xs text-zinc-300">
          <thead className="bg-[#242424] text-zinc-300">
            <tr>
              <th className="border border-zinc-700 px-3 py-2">目标数字</th>
              <th className="border border-zinc-700 px-3 py-2">
                预测下次出现（日期范围）
              </th>
              <th className="border border-zinc-700 px-3 py-2">样本数 n</th>
              <th className="border border-zinc-700 px-3 py-2">平均间隔(天)</th>
              <th className="border border-zinc-700 px-3 py-2">±1σ</th>
              <th className="border border-zinc-700 px-3 py-2">最近一次(天)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const active = activeNumbers.includes(row.number);
              const prediction = row.prediction;
              const conditional = prediction?.conditional === true;
              return (
                <tr
                  key={row.number}
                  className={
                    conditional
                      ? "bg-amber-950/40 text-amber-100"
                      : active
                        ? "bg-[#40391f] text-[#f2e7bd]"
                        : "bg-zinc-900"
                  }
                >
                  <td
                    className={`sticky left-0 border border-zinc-800 bg-inherit px-3 py-2 font-semibold ${active && !conditional ? "text-amber-200" : ""}`}
                  >
                    {row.number}
                    {active && row.number === activeNumbers[0] ? "?" : ""}
                  </td>
                  <td
                    className={`border border-zinc-800 px-3 py-2 font-semibold ${conditional ? "text-amber-200" : active ? "text-[#f5b7b8]" : "text-rose-300"}`}
                  >
                    {prediction ? (
                      <>
                        {prediction.lo_date} ～ {prediction.hi_date}
                        {prediction.constraint_applied ? " †" : ""}
                        {prediction.candidate_window_rebased ? " ‡" : ""}
                        {prediction.overlaps_previous_window && (
                          <span className="mt-1 block text-[11px] font-normal leading-4 text-amber-200">
                            ⚠ 与 #{prediction.previous_number} 时间窗重叠
                            {prediction.overlap_start && prediction.overlap_end
                              ? `（${prediction.overlap_start} ～ ${prediction.overlap_end}）`
                              : ""}
                            {prediction.requires_previous_confirmation
                              ? "；条件预测，待前序点确认"
                              : "；保留为统计区间"
                            }
                          </span>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="border border-zinc-800 px-3 py-2">
                    {row.sample_count}
                  </td>
                  <td className="border border-zinc-800 px-3 py-2">
                    {formatDays(row.mean_days)}
                  </td>
                  <td className="border border-zinc-800 px-3 py-2">
                    {formatDays(row.std_days, "±")}
                  </td>
                  <td className="border border-zinc-800 px-3 py-2">
                    {formatDays(row.last_interval_days)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
