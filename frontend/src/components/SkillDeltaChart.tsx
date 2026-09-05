/** Compatibility bridge for existing compact App call sites.
 * The DELTA implementation now lives in TerminalChart so it shares the
 * native pan/zoom time axis with the original GPMAPRO drawing engine.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  TerminalChart,
  type ChartBar,
  type ChartLayer,
  type ChanlunAnalysis,
  type DeltaAnalysis,
  type GpmaSeries,
} from "./TerminalChart";

const reversalLabels = {
  NORMAL: ["常态映射", "当前没有处于可识别的倒转时间窗。"],
  ITW_WATCH: ["倒转观察窗口", "正在观察 M → 1 → 2；映射仍保持常态。"],
  AI_WATCH: ["AI 倒转预警", "概率达到观察阈值，但没有经硬规则确认的倒转。"],
  INVERSION_CONFIRMED: [
    "倒转已确认",
    "检测到一个合格 IBP，后续 HIGH / LOW 映射已翻转。",
  ],
  DOUBLE_INVERSION_CONFIRMED: [
    "双倒转已确认",
    "检测到两个合格 IBP，映射已恢复为原方向。",
  ],
} as const;

function ReversalPanel({ analysis }: { analysis?: DeltaAnalysis }) {
  const reversal = analysis?.reversal;
  const state = reversal?.state ?? "NORMAL";
  const [title, description] = reversalLabels[state];
  const isInverted = state === "INVERSION_CONFIRMED";
  const isDouble = state === "DOUBLE_INVERSION_CONFIRMED";
  const tone = isInverted
    ? "reversal-inverted"
    : isDouble
      ? "reversal-double"
      : state === "AI_WATCH"
        ? "reversal-ai"
        : "reversal-normal";
  const activeWindow = reversal?.windows?.at(-1);
  return (
    <section
      className={`reversal-panel mb-4 ${tone}`}
      aria-label="DELTA 倒转状态"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="reversal-kicker">DELTA ITW · Reversal</p>
          <h2>{title}</h2>
          <p className="reversal-description">{description}</p>
        </div>
        <div className="reversal-state">
          <span>当前状态</span>
          <strong>{state}</strong>
        </div>
      </div>
      <div className="reversal-metrics">
        <div>
          <span>ITW 区间</span>
          <strong>
            {activeWindow?.display_start ?? "—"} →{" "}
            {activeWindow?.display_end ?? "—"}
          </strong>
        </div>
        <div>
          <span>确认 IBP / 阈值</span>
          <strong>
            {reversal?.ibps?.length ?? 0} 个 /{" "}
            {reversal?.ai?.available
              ? `${Math.round((reversal.ai.threshold ?? 0) * 100)}%`
              : "AI 不可用"}
          </strong>
        </div>
        <div>
          <span>生效规则</span>
          <strong>确认日后下一交易日</strong>
        </div>
      </div>
      {(reversal?.ibps?.length ?? 0) > 0 && (
        <div className="reversal-table">
          <table className="min-w-[640px] text-left text-xs">
            <thead>
              <tr>
                <th>IBP</th>
                <th>类型</th>
                <th>AI 概率</th>
                <th>确认日期</th>
                <th>可交易日期</th>
              </tr>
            </thead>
            <tbody>
              {reversal!.ibps!.map((ibp) => (
                <tr key={ibp.id}>
                  <td className="font-mono font-semibold">{ibp.label}</td>
                  <td>{ibp.type}</td>
                  <td>
                    {ibp.ai?.probability == null
                      ? "—"
                      : `${Math.round(ibp.ai.probability * 100)}%`}
                  </td>
                  <td>{ibp.confirmed_on}</td>
                  <td>{ibp.tradable_on ?? "待确认"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function SkillDeltaChart({
  bars,
  analysis,
  gpma = [],
  gpma2 = [],
  gpma2Status,
  gpma2Loading = false,
  gpma2Error,
  focusDate,
  showReversal = true,
  compact = false,
  mode,
  analysisLoading = false,
  analysisError,
  layer,
  chanlun,
  onLayerChange,
}: {
  bars: ChartBar[];
  analysis?: DeltaAnalysis;
  gpma?: GpmaSeries[];
  gpma2?: GpmaSeries[];
  gpma2Status?: "not_reconciled" | "matched" | "drift";
  gpma2Loading?: boolean;
  gpma2Error?: string;
  focusDate?: string;
  showReversal?: boolean;
  compact?: boolean;
  mode?: "overview" | "research";
  analysisLoading?: boolean;
  analysisError?: string;
  layer?: ChartLayer;
  chanlun?: ChanlunAnalysis;
  onLayerChange?: (layer: ChartLayer) => void;
}) {
  const client = useQueryClient();
  // Older compact call sites do not pass their series yet.  In that case,
  // select only a cache entry whose formula close values match these exact
  // candles.  A first-nonempty cache lookup could combine two symbols (or two
  // adjustment modes) on one price scale and visually split the chart.
  const barClose = new Map(bars.map((bar) => [bar.time, bar.close]));
  const requestedTimeframe = analysis?.timeframe;
  const candidates = ["gpmapro-series", "gpmapro-workbench"].flatMap((key) =>
    client
      .getQueriesData<{ series: GpmaSeries[] }>({ queryKey: [key] })
      // A monthly close also occurs on a daily series.  Require the cache key's
      // explicit timeframe before comparing closes, otherwise daily EMA points
      // pollute the weekly/monthly native chart axis.
      .filter(
        ([queryKey]) =>
          !requestedTimeframe ||
          (Array.isArray(queryKey) && queryKey.includes(requestedTimeframe)),
      )
      .map(([, value]) => value?.series ?? []),
  );
  const compatible = candidates
    .map((series) => {
      const deltas = series.flatMap((row) => {
        const close = barClose.get(row.time);
        return typeof row.close === "number" &&
          typeof close === "number" &&
          close !== 0
          ? [Math.abs(row.close - close) / Math.abs(close)]
          : [];
      });
      return {
        series,
        error:
          deltas.length >= 3
            ? deltas.reduce((sum, value) => sum + value, 0) / deltas.length
            : Infinity,
      };
    })
    .sort((left, right) => left.error - right.error);
  const matchedGpma = gpma.length
    ? gpma
    : compatible[0]?.error < 0.001
      ? compatible[0].series
      : [];
  const windows = (analysis?.points ?? []).map((point) => ({
    event_id: point.id,
    event_type: point.type,
    actual_date: point.date,
    confirmed_on: point.confirmed ? point.date : null,
    confirmed: point.confirmed,
  }));
  return (
    <>
      {showReversal && <ReversalPanel analysis={analysis} />}
      <TerminalChart
        bars={bars}
        gpma={matchedGpma}
        gpma2={gpma2}
        gpma2Status={gpma2Status}
        gpma2Loading={gpma2Loading}
        gpma2Error={gpma2Error}
        deltaWindows={windows}
        deltaAnalysis={analysis}
        focusDate={focusDate}
        compact={compact}
        mode={mode}
        deltaAnalysisLoading={analysisLoading}
        deltaAnalysisError={analysisError}
        layer={layer}
        chanlun={chanlun}
        onLayerChange={onLayerChange}
      />
    </>
  );
}
