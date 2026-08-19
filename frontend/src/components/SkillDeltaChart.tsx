/** Compatibility bridge for existing compact App call sites.
 * The DELTA implementation now lives in TerminalChart so it shares the
 * native pan/zoom time axis with the original GPMAPRO drawing engine.
 */
import { useQueryClient } from "@tanstack/react-query";
import { TerminalChart, type ChartBar, type DeltaAnalysis, type GpmaSeries } from "./TerminalChart";

export function SkillDeltaChart({ bars, analysis, gpma = [] }: { bars: ChartBar[]; analysis?: DeltaAnalysis; gpma?: GpmaSeries[] }) {
  const client = useQueryClient();
  // Older compact call sites do not pass their series yet.  In that case,
  // select only a cache entry whose formula close values match these exact
  // candles.  A first-nonempty cache lookup could combine two symbols (or two
  // adjustment modes) on one price scale and visually split the chart.
  const barClose = new Map(bars.map((bar) => [bar.time, bar.close]));
  const requestedTimeframe = analysis?.timeframe;
  const candidates = ["gpmapro-series", "gpmapro-workbench"].flatMap((key) => client.getQueriesData<{ series: GpmaSeries[] }>({ queryKey: [key] })
    // A monthly close also occurs on a daily series.  Require the cache key's
    // explicit timeframe before comparing closes, otherwise daily EMA points
    // pollute the weekly/monthly native chart axis.
    .filter(([queryKey]) => !requestedTimeframe || (Array.isArray(queryKey) && queryKey.includes(requestedTimeframe)))
    .map(([, value]) => value?.series ?? []));
  const compatible = candidates.map((series) => {
    const deltas = series.flatMap((row) => {
      const close = barClose.get(row.time);
      return typeof row.close === "number" && typeof close === "number" && close !== 0 ? [Math.abs(row.close - close) / Math.abs(close)] : [];
    });
    return { series, error: deltas.length >= 3 ? deltas.reduce((sum, value) => sum + value, 0) / deltas.length : Infinity };
  }).sort((left, right) => left.error - right.error);
  const matchedGpma = gpma.length ? gpma : (compatible[0]?.error < 0.001 ? compatible[0].series : []);
  const windows = (analysis?.points ?? []).map((point) => ({ event_id: point.id, event_type: point.type, actual_date: point.date, confirmed_on: point.confirmed ? point.date : null, confirmed: point.confirmed }));
  return <TerminalChart bars={bars} gpma={matchedGpma} deltaWindows={windows} deltaAnalysis={analysis} />;
}
