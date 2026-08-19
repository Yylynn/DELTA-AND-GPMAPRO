import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

const request = async (path: string) => { const response = await fetch(path); if (!response.ok) throw new Error(await response.text()); return response.json(); };
type Snapshot = { snapshot_id: string; code: string; timeframe: string; autype: string; fetched_at: string; start_date: string; end_date: string; bar_count: number };
type Diagnostics = { rows: Array<Record<string, string | number | boolean>> };
type Trace = { trace_id: string; reference: string; rows: number; start_date: string; end_date: string };
type Reconciliation = { comparison: { overlap_rows: number; fields: Record<string, { mismatched: number }> } };

export function FutuReconciliationPanel({ snapshotId, symbol }: { snapshotId?: string; symbol: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [traceId, setTraceId] = useState("");
  const diagnostics = useQuery<Diagnostics>({ queryKey: ["futu-gpma-diagnostics", symbol, snapshotId], queryFn: () => request(`/api/gpmapro/${encodeURIComponent(symbol)}/diagnostics?snapshot_id=${encodeURIComponent(snapshotId ?? "")}`), enabled: Boolean(snapshotId && symbol), retry: false });
  const traces = useQuery<{ traces: Trace[] }>({ queryKey: ["gpmapro-traces"], queryFn: () => request("/api/gpmapro/traces"), retry: false });
  const reconciliation = useQuery<Reconciliation>({ queryKey: ["gpmapro-reconciliation", symbol, snapshotId, traceId], queryFn: () => request(`/api/gpmapro/${encodeURIComponent(symbol)}/reconciliation?snapshot_id=${encodeURIComponent(snapshotId ?? "")}&trace_id=${encodeURIComponent(traceId)}`), enabled: Boolean(snapshotId && traceId && symbol), retry: false });
  const upload = async () => {
    if (!file) return;
    const body = new FormData(); body.append("file", file);
    const response = await fetch("/api/gpmapro/traces/import?reference=futu_desktop_export", { method: "POST", body });
    if (!response.ok) throw new Error(await response.text());
    const imported: Trace = await response.json(); setTraceId(imported.trace_id); setFile(null); await traces.refetch();
  };
  const rows = diagnostics.data?.rows ?? [];
  const mismatches = reconciliation.data ? Object.entries(reconciliation.data.comparison.fields).filter(([, field]) => field.mismatched > 0) : [];
  return <section className="panel mt-4 overflow-hidden p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="panel-title">富途公式对账诊断</div><p className="mt-1 text-xs text-zinc-500">显示最终节点及原始条件。导入富途 TRACE CSV 后，系统会按日期逐字段比较。</p></div>{snapshotId && <code className="text-xs text-cyan-300">{snapshotId}</code>}</div>
    <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-zinc-800 py-3"><input className="terminal-input max-w-xs" type="file" accept=".csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><button className="primary-button" disabled={!file} onClick={() => void upload()}>导入富途 TRACE CSV</button><select className="terminal-input max-w-xs" value={traceId} onChange={(event) => setTraceId(event.target.value)}><option value="">选择已导入 TRACE</option>{traces.data?.traces.map((trace) => <option key={trace.trace_id} value={trace.trace_id}>{trace.start_date} → {trace.end_date} · {trace.reference}</option>)}</select></div>
    {reconciliation.data && <div className="mt-3 text-xs text-zinc-400">重叠 {reconciliation.data.comparison.overlap_rows} 日；{mismatches.length ? <span className="text-rose-300">差异字段：{mismatches.map(([field, value]) => `${field} (${value.mismatched})`).join("、")}</span> : <span className="text-emerald-300">已导入字段全部一致</span>}</div>}
    {diagnostics.isError ? <p className="mt-3 text-sm text-rose-300">无法加载富途快照诊断。</p> : <div className="mt-3 max-h-64 overflow-auto"><table><thead><tr><th>日期</th><th>收盘</th><th>ATR</th><th>B/S</th><th>一级脸部</th><th>二级箭头</th><th>三级箭头</th><th>原始条件</th></tr></thead><tbody>{rows.length ? rows.map((row) => { const on = (keys: string[]) => keys.filter((key) => row[key]).join(" / ") || "—"; return <tr key={String(row.date)}><td>{String(row.date)}</td><td>{Number(row.close).toFixed(2)}</td><td>{Number(row.atr_26).toFixed(2)}</td><td>{on(["b1", "b2", "b3", "s1", "s2"])}</td><td>{on(["top_face", "bottom_face"])}</td><td>{on(["top_2", "bottom_2"])}</td><td>{on(["top_3", "bottom_3"])}</td><td>{on(["top_1_raw", "bottom_1_raw", "top_2_raw", "bottom_2_raw", "top_3_raw", "bottom_3_raw"])}</td></tr>; }) : <tr><td colSpan={8}>当前快照没有最终节点；不会用视觉标记伪造信号。</td></tr>}</tbody></table></div>}
  </section>;
}

export type { Snapshot };
