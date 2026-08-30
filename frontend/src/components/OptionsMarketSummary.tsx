import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { StatusBadge } from "@/components/ui/workspace";

type Alert = { id: string; symbol: string; created_at: string; scheduled_event: boolean; signals: Array<{ kind: string; severity: string }>; relation: { kind: string } };
type Monitor = { health: { status: string; error?: string | null }; alerts: Alert[]; unread_count: number; last_check?: { captured_at: string } | null };
async function request<T>(path: string, init?: RequestInit): Promise<T> { const response = await fetch(path, init); if (!response.ok) throw new Error(await response.text()); return response.json(); }
const formatTime = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";

export function OptionsMarketSummary({ onOpenOptions }: { onOpenOptions: () => void }) {
  const [running, setRunning] = useState(false); const monitor = useQuery({ queryKey: ["option-market-summary"], queryFn: () => request<Monitor>("/api/options/monitor"), retry: false });
  const scan = async () => { setRunning(true); try { await request("/api/options/monitor/check", { method: "POST" }); await monitor.refetch(); } finally { setRunning(false); } };
  return <section className="panel news-options-market-summary"><div className="news-subheading"><div><span className="news-eyebrow">OPTIONS MARKET PULSE</span><h3>市场期权情绪摘要</h3><p>用于宏观风险背景，不替代独立期权链分析。</p></div><div className="flex gap-2"><button className="secondary-button inline-flex items-center gap-1" onClick={() => void scan()} disabled={running}><RefreshCw size={14}/>{running ? "扫描中" : "扫描候选池"}</button><button className="primary-button inline-flex items-center gap-1" onClick={onOpenOptions}>进入期权雷达<ArrowUpRight size={14}/></button></div></div><div className="grid grid-cols-3 gap-3 text-sm"><div><span>数据状态</span><b><StatusBadge tone={monitor.data?.health.status === "AVAILABLE" ? "positive" : "warning"}>{monitor.data?.health.status || "检查中"}</StatusBadge></b></div><div><span>未读异常</span><b>{monitor.data?.unread_count ?? "—"}</b></div><div><span>最新扫描</span><b>{formatTime(monitor.data?.last_check?.captured_at)}</b></div></div>{monitor.data?.health.error && <p className="text-rose-300 text-sm mt-3">{monitor.data.health.error}</p>}<div className="mt-3 space-y-2">{(monitor.data?.alerts ?? []).slice(0, 5).map(alert => <button className="w-full text-left rounded border border-zinc-800 p-2 hover:bg-zinc-900" onClick={onOpenOptions} key={alert.id}><strong>{alert.symbol}</strong><span className="ml-2 text-xs text-zinc-400">{alert.signals.map(item => item.kind).join(" · ") || "异常"}</span><span className="float-right text-xs text-zinc-500">{alert.scheduled_event ? "事件降权" : alert.relation.kind}</span></button>)}{!monitor.isLoading && !(monitor.data?.alerts.length) && <p className="muted text-sm">当前没有期权异常预警；预热完成后仅显示显著异动。</p>}</div></section>;
}
