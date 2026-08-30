import { useState } from "react";
import { Button, InlineLoading, Tag } from "@carbon/react";
import { PanelHeading } from "@/components/ui/workspace";

type Row = {
  rule_id: string;
  split: string;
  rule: { indicator_version: string; entry_anchor: string; delta_lookback?: number | null; exit_rule?: string; holding_days: number; cost_bps_per_side: number };
  metrics: { sample_count: number; average_net_return: number | null; net_return_ci_95: [number | null, number | null] };
  incremental_net_return?: number | null;
  equity_return?: number;
  max_drawdown?: number;
  turnover?: number;
  research_status?: string;
};
type Result = { protocol_id: string; single_signal: Row[]; delta_incremental: Row[]; portfolio_replays: Row[]; lockbox: Row[]; walk_forward: { positive_window_rate: number | null }; signal_protocol: { gpma2_notice: string } };
const percent = (value: number | null | undefined) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;

function statusTone(value?: string) {
  return value === "研究候选" ? "green" : value === "已拒绝" ? "red" : "gray";
}

export function SignalRuleResearch() {
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setLoading(true); setError(null);
    try {
      const response = await fetch("/api/backtest/signal-rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ protocol_id: "US_ETF_SHORT_V1" }) });
      if (!response.ok) throw new Error(await response.text());
      setResult(await response.json());
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };
  const select = (rows: Row[]) => rows.filter(row => row.split === "SELECT" && row.rule.cost_bps_per_side === 10).slice(0, 80);
  const lockbox = result?.lockbox ?? [];
  return <section className="panel mt-4 p-4">
    <PanelHeading title="DELTA × GPMAPRO 短线规则研究" description="固定 US_ETF_SHORT_V1：T 日收盘确认、T+1 开盘成交；仅研究与纸面交易，不产生自动下单。" meta="预登记协议 · 长仓 · 最大 5 日" />
    <div className="mt-3 flex items-center gap-3">
      <Button size="sm" onClick={() => void run()} disabled={loading}>{loading ? <InlineLoading description="正在重放 DELTA 历史预测…" /> : "运行固定研究"}</Button>
      {result && <Tag type="cyan" size="sm">{result.protocol_id}</Tag>}
      {result?.walk_forward.positive_window_rate != null && <span className="text-xs text-zinc-400">Walk-forward 正窗口：{percent(result.walk_forward.positive_window_rate)}</span>}
    </div>
    {error && <p className="error-banner mt-3">{error}</p>}
    {!result && <p className="panel-footnote mt-3">覆盖 SPY、QQQ、IWM、DIA、XLK、XLF、XLE、TLT。首次运行会逐日冻结 DELTA 当时可知的预测，因此比一般指标回测更慢。</p>}
    {result && <>
      <p className="panel-footnote mt-3">{result.signal_protocol.gpma2_notice}</p>
      <ResearchTable title="哪一个图标可作为入场锚点" description="单信号在选择集的 1/3/5 日净收益（10bp 单边成本）。连续图标只记首次出现。" rows={select(result.single_signal)} mode="single" />
      <ResearchTable title="DELTA 最近几日是否增益" description="只显示探索集已通过初筛的主信号。增量 = DELTA LOW + 主信号 − 主信号单独。" rows={select(result.delta_incremental)} mode="delta" />
      <ResearchTable title="真实怎么卖" description="同一买入规则的实际长仓回放；S 只平仓，不把下跌计作假想做空。" rows={select(result.portfolio_replays)} mode="replay" />
      <div className="mt-4 border-t border-zinc-800 pt-3"><b className="text-sm">锁箱结论（规则冻结后使用）</b><div className="mt-2 flex flex-wrap gap-2">{lockbox.length ? lockbox.map(row => <Tag key={row.rule_id} type={statusTone(row.research_status) as "green"}>{row.research_status ?? "证据不足"} · {row.rule.entry_anchor} / {row.rule.exit_rule}</Tag>) : <span className="text-xs text-zinc-500">没有通过探索筛选的退出组合；这本身不是买卖结论。</span>}</div></div>
    </>}
  </section>;
}

function ResearchTable({ title, description, rows, mode }: { title: string; description: string; rows: Row[]; mode: "single" | "delta" | "replay" }) {
  return <div className="mt-5 overflow-x-auto border-t border-zinc-800 pt-4">
    <b className="text-sm">{title}</b><p className="mb-2 text-xs text-zinc-500">{description}</p>
    <table><thead><tr><th>版本</th><th>锚点</th>{mode !== "single" && <th>DELTA L</th>}{mode === "replay" && <th>退出</th>}<th>持有</th><th>样本</th><th>{mode === "delta" ? "边际净收益" : "平均净收益"}</th>{mode === "replay" && <><th>账户收益</th><th>最大回撤</th><th>换手</th></>}</tr></thead>
      <tbody>{rows.length ? rows.map(row => <tr key={`${row.rule_id}-${row.split}`}><td>{row.rule.indicator_version}</td><td>{row.rule.entry_anchor}</td>{mode !== "single" && <td>{row.rule.delta_lookback ?? "—"}</td>}{mode === "replay" && <td>{row.rule.exit_rule}</td>}<td>{row.rule.holding_days} 日</td><td>{row.metrics.sample_count}</td><td>{percent(mode === "delta" ? row.incremental_net_return : row.metrics.average_net_return)}</td>{mode === "replay" && <><td>{percent(row.equity_return)}</td><td>{percent(row.max_drawdown)}</td><td>{row.turnover ?? 0}</td></>}</tr>) : <tr><td colSpan={mode === "replay" ? 10 : mode === "delta" ? 7 : 5}>当前没有符合预登记筛选条件的记录。</td></tr>}</tbody>
    </table>
  </div>;
}
