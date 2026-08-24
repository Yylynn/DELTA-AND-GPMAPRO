import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Evidence = { source: string; direction: "BULLISH" | "BEARISH"; label: string; date: string; detail: string };
type Signal = { code: string; date: string; bars_since: number };
type Indicator = { indicator: "GPMAPRO" | "GPMA2"; source_status: string; script_sha256?: string | null; trend: string; direction: string; bullish_signals: Signal[]; bearish_signals: Signal[]; bullish_divergences: Signal[]; bearish_divergences: Signal[] };
type Action = "BUY" | "ACCUMULATE" | "HOLD" | "REDUCE" | "SELL";
type Audit = { bars: number; action_counts: Partial<Record<Action, number>>; blocked_by: Array<{ reason: string; count: number }>; candidates: Array<{ date: string; action: Action; label: string; eligible: boolean; blocked_by: string[] }> };
type SignalDetail = { source: "DELTA" | "GPMAPRO" | "GPMA2"; signal_code: string; date: string; plain_language: string; market_context: string; action_impact: string; confidence: string; why_now: string; what_invalidates_it: string };
type NewsOverlay = { status: string; action: Action; bias: string; score: number; confidence: number; validation_status: string; reason: string; base_action: Action; base_action_strength: number; action_strength: number; requested_points: number; applied_points: number; effect: "NONE" | "CONFIRM" | "DOWNGRADE" };
type Driver = { id: string; title: string; status: string; detail: string; date?: string | null; detail_target?: "NEWS_CENTER" };
type Interpretation = { base_action: Action; base_action_label: string; base_action_strength: number; action: Action; action_label: string; action_strength: number; position_guidance: string; news_overlay: NewsOverlay; rule_id: string; next_steps: string[]; as_of: string; drivers: Driver[]; evidence: Evidence[]; signal_details: SignalDetail[]; missing_conditions: string[]; conflicts: string[]; blocked_by: string[]; audit?: Audit; indicators: Indicator[]; validation: { status: string; message: string } };

async function getInterpretation(path: string): Promise<Interpretation> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

const actionClass: Record<Action, string> = {
  BUY: "decision-action-buy",
  ACCUMULATE: "decision-action-accumulate",
  HOLD: "decision-action-hold",
  REDUCE: "decision-action-reduce",
  SELL: "decision-action-sell",
};

const driverClass = (status: string) => {
  if (status === "BULLISH" || status === "AVAILABLE") return "driver-positive";
  if (status === "BEARISH") return "driver-negative";
  if (status === "CONFLICT") return "driver-conflict";
  return "driver-neutral";
};

/** Concise long-only action dashboard. It has no broker or order controls. */
export function SignalInterpretation({ symbol, timeframe, snapshotId, onFocusDate, onOpenNews }: { symbol: string; timeframe: string; snapshotId?: string; onFocusDate: (date: string) => void; onOpenNews?: (symbol: string) => void }) {
  const [selectedDetail, setSelectedDetail] = useState<SignalDetail["source"] | null>(null);
  const snapshotQuery = snapshotId ? `&snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  const query = useQuery<Interpretation>({ queryKey: ["signal-interpretation", symbol, timeframe, snapshotId], queryFn: () => getInterpretation(`/api/interpretation/${encodeURIComponent(symbol)}?timeframe=${timeframe}${snapshotQuery}`), enabled: Boolean(snapshotId), retry: false });
  const data = query.data;

  if (query.isLoading) return <section className="panel mt-4 p-4 text-sm text-zinc-400">正在计算行动建议…</section>;
  if (query.isError) return <section className="error-banner mt-4">行动建议不可用：{query.error instanceof Error ? query.error.message : "未知错误"}</section>;
  if (!data) return null;

  const focus = (date?: string | null) => () => { if (date) onFocusDate(date); };
  const risks = [...data.conflicts, ...data.missing_conditions].slice(0, 2);
  const detailSource = (id: string): SignalDetail["source"] | null => id === "delta" ? "DELTA" : id === "gpmapro" ? "GPMAPRO" : id === "gpma2" ? "GPMA2" : null;
  const openDriver = (driver: Driver) => {
    if (driver.detail_target === "NEWS_CENTER" || driver.id === "news") {
      onOpenNews?.(symbol);
      return;
    }
    const source = detailSource(driver.id);
    if (source) setSelectedDetail(source);
  };
  const currentDetails = selectedDetail ? data.signal_details.filter(item => item.source === selectedDetail) : [];

  return <section className={`decision-panel mt-4 ${actionClass[data.action]}`} aria-label="当前行动建议">
    <header className="decision-summary">
      <div className="decision-action">
        <p className="decision-kicker">当前行动建议 <span>仅多头仓位管理</span></p>
        <div className="decision-action-row"><h2>{data.action_label}</h2><span className="decision-action-badge">{data.action}</span></div>
        <p className="decision-guidance">{data.position_guidance}</p>
      </div>
      <div className="decision-strength">
        <div className="decision-section-label"><span>行动强度</span><b>{data.action_strength} <small>/ 100</small></b></div>
        <div className="decision-progress" aria-label={`行动强度 ${data.action_strength} / 100`}><span style={{ width: `${data.action_strength}%` }}/></div>
        <div className="decision-overlay-summary"><span>技术结论 {data.base_action_label}</span><b className={data.news_overlay.applied_points < 0 ? "is-negative" : data.news_overlay.applied_points > 0 ? "is-positive" : ""}>新闻调整 {data.news_overlay.applied_points > 0 ? "+" : ""}{data.news_overlay.applied_points.toFixed(2)}</b></div>
        <p>截至 {data.as_of} <i/> {data.rule_id}</p>
      </div>
      <div className="decision-next-step">
        <p className="decision-section-label">现在最需要等什么</p>
        <p>{data.next_steps[0]}</p>
        <small>规则提示：不自动下单；卖出仅表示减仓或清仓。</small>
      </div>
    </header>

    <div className="decision-body">
      <section aria-label="策略驱动"><div className="decision-area-heading"><div><p className="decision-kicker">策略驱动</p><h3>结论由这些条件共同约束</h3></div><span>{data.drivers.length} 项验证</span></div>
        <div className="decision-driver-grid">{data.drivers.map(driver => <article className={`decision-driver ${driverClass(driver.status)}`} key={driver.id}>
          <div className="decision-driver-heading"><span>{driver.title}</span><b>{driver.status}</b></div><p>{driver.detail}</p>
          <div className="decision-driver-actions">{driver.date && <button type="button" onClick={focus(driver.date)}>定位 {driver.date}</button>}<button type="button" onClick={() => openDriver(driver)}>{driver.id === "news" ? "新闻详情" : "查看详情"}</button></div>
        </article>)}</div>
      </section>

      {selectedDetail && <section className="decision-detail" aria-label={`${selectedDetail} 信号详情`}><div className="decision-area-heading"><div><p className="decision-kicker">{selectedDetail} 信号详情</p><h3>当前快照的实际触发依据</h3><p className="decision-detail-intro">这里解释的是 {symbol} 当前快照中的实际触发信号，而非通用买卖承诺。</p></div><button className="decision-text-button" type="button" onClick={() => setSelectedDetail(null)}>收起</button></div>
        {currentDetails.length ? <div className="decision-detail-grid">{currentDetails.map(item => <article className="decision-detail-card" key={`${item.source}-${item.signal_code}-${item.date}`}><div><button className="decision-signal-link" type="button" onClick={focus(item.date)}>{item.signal_code} <i/> {item.date}</button><span>{item.confidence}</span></div><p>{item.plain_language}</p><dl><div><dt>对这只股票的解读</dt><dd>{item.market_context}</dd></div><div><dt>行动影响</dt><dd>{item.action_impact}</dd></div><div><dt>为何现在出现</dt><dd>{item.why_now}</dd></div><div><dt>何时失效</dt><dd>{item.what_invalidates_it}</dd></div></dl></article>)}</div> : <p className="decision-empty">当前没有可展开的近期信号；该指标仍会在出现新信号时自动更新。</p>}
      </section>}

      <section className="decision-conditions" aria-label="决策条件"><article className="decision-condition"><p>升级 / 降级条件</p><b>后续验证</b><span>{data.next_steps.slice(1).join("；") || data.next_steps[0]}</span></article><article className="decision-condition decision-risk"><p>风险与否决项</p><b>需要关注</b><span>{risks.join("；") || "当前无额外否决项。"}</span></article></section>

      {data.audit && <section className="decision-audit" aria-label="行动审计"><div className="decision-area-heading"><div><p className="decision-kicker">审计记录</p><h3>近 {data.audit.bars} 日行动审计</h3></div><span>同一快照逐日截断</span></div><div className="decision-audit-summary"><div className="decision-counts">{(["BUY", "ACCUMULATE", "HOLD", "REDUCE", "SELL"] as Action[]).map(action => <span className={actionClass[action]} key={action}>{action}<b>{data.audit?.action_counts[action] ?? 0}</b></span>)}</div><p>{data.audit.blocked_by.length ? `主要拦截：${data.audit.blocked_by.slice(0, 2).map(item => `${item.reason} (${item.count})`).join("；")}` : "没有被规则拦截的候选。"}</p></div>{data.audit.candidates.length > 0 && <div className="decision-candidates">{data.audit.candidates.slice(-8).map(item => <button className={item.eligible ? "is-eligible" : ""} type="button" key={`${item.date}-${item.action}`} onClick={focus(item.date)} title={item.blocked_by.join("；")}>{item.date} <i/> {item.label}{item.eligible ? " · 候选" : ""}</button>)}</div>}</section>}
    </div>

    <details className="decision-evidence"><summary>查看证据明细与双版本状态</summary><div className="decision-evidence-content"><div className="decision-evidence-grid">{data.indicators.map(indicator => { const signals = [...indicator.bullish_signals, ...indicator.bearish_signals, ...indicator.bullish_divergences, ...indicator.bearish_divergences]; return <article className="decision-evidence-card" key={indicator.indicator}><div><b>{indicator.indicator}</b><span>{indicator.direction} <i/> 趋势 {indicator.trend}</span></div><p>{indicator.indicator === "GPMAPRO" ? "稳定基线：已接入现有证据与回测" : indicator.source_status === "AVAILABLE" ? `富途脚本 ${indicator.script_sha256?.slice(0, 10) ?? "-"}` : "研究确认层：本地等价绘图回退，可影响适当等级，不单独买入或卖出"}</p><div>{signals.length ? signals.map(signal => <button type="button" key={`${signal.code}-${signal.date}`} onClick={focus(signal.date)}>{signal.code} <i/> {signal.date}</button>) : <span>近期无最终 B/S 或背离确认</span>}</div></article>; })}</div><article className="decision-validation"><b>校准状态：{data.validation.status}</b><p>{data.validation.message}</p></article>{data.evidence.length > 0 && <div className="decision-evidence-links">{data.evidence.map((item, index) => <button type="button" key={`${item.source}-${item.label}-${index}`} title={item.detail} onClick={focus(item.date)}>{item.source} <i/> {item.label} <i/> {item.date}</button>)}</div>}</div></details>
  </section>;
}
