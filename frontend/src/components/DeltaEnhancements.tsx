import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

const request = async (path: string, options?: RequestInit) => { const r = await fetch(path, options); if (!r.ok) throw new Error(await r.text()); return r.json(); };

export function DeltaEnhancements() {
  const [file, setFile] = useState<File | null>(null); const [result, setResult] = useState<any>(null); const [symbol, setSymbol] = useState("VXN");
  const coverage = useQuery<any>({ queryKey: ["delta-coverage", symbol], queryFn: () => request("/api/diagnostics/decisions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbols: [symbol], sampling_mode: "TRANSITION" }) }) });
  const upload = async () => { if (!file) return; const body = new FormData(); body.append("file", file); setResult(await request("/api/delta/import", { method: "POST", body })); await coverage.refetch(); };
  const funnel = coverage.data?.delta_funnel ?? {};
  const labels: Record<string, string> = { configured_events: "已配置事件", events_inside_data_range: "数据范围内", delta_low_events: "LOW 事件", delta_high_events: "HIGH 事件", active_windows: "活动窗口", evidence_snapshots: "证据快照", decision_confirmations: "决策确认" };
  return <div className="terminal-page pt-0"><section className="panel p-4"><div className="panel-title">批量导入 DELTA 事件</div><p className="muted">CSV 字段：symbol、event_type、anchor_date、published_at、expected_date、tolerance_days、confidence、enabled；未提供 published_at 时使用 anchor_date。</p><div className="mt-3 flex gap-2"><input className="terminal-input" type="file" accept=".csv" onChange={e => setFile(e.target.files?.[0] ?? null)}/><button className="primary-button" disabled={!file} onClick={() => void upload()}>导入事件</button><a className="text-button" href="/api/delta/import-template" target="_blank">下载模板</a></div>{result && <p className="mt-2 text-sm">已导入 {result.imported} · 重复 {result.duplicates} · 冲突 {result.conflicts} · 已拒绝 {result.rejected}</p>}</section><section className="panel mt-4 p-4"><div className="toolbar"><div className="panel-title">DELTA 覆盖</div><input className="terminal-input w-24" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}/></div><div className="mt-3 grid grid-cols-4 gap-3 text-sm">{Object.keys(labels).map(key => <div className="border border-zinc-800 p-3" key={key}><span>{labels[key]}</span><b>{String(funnel[key] ?? "—")}</b></div>)}</div></section></div>;
}
