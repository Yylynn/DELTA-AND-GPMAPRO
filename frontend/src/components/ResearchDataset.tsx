import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

const request = async (path: string, options?: RequestInit) => { const r = await fetch(path, options); if (!r.ok) throw new Error(await r.text()); return r.json(); };
type SymbolRow = { symbol: string; bars: number; start_date: string; end_date: string; freshness: string; research_eligibility: string };
type Coverage = { eligible_symbols: number; required_symbols: number; basket_coverage: number; status: string; basket: Array<{ symbol: string; category: string; eligible: boolean }> };
type FutuCoverage = { eligible_symbols: number; required_symbols: number; status: string; symbols: Array<{ symbol: string; code: string; snapshot_id: string | null; bars: number; start_date: string | null; end_date: string | null; freshness: string; research_eligibility: string }> };

export function ResearchDataset() {
  const [files, setFiles] = useState<File[]>([]); const [result, setResult] = useState<any>(null); const [futuResult, setFutuResult] = useState<any>(null);
  const symbols = useQuery<{ symbols: SymbolRow[] }>({ queryKey: ["research-universe"], queryFn: () => request("/api/data/symbols") });
  const coverage = useQuery<Coverage>({ queryKey: ["research-coverage"], queryFn: () => request("/api/data/coverage") });
  const futuCoverage = useQuery<FutuCoverage>({ queryKey: ["futu-research-coverage"], queryFn: () => request("/api/data/futu/research-coverage") });
  const upload = async () => { const body = new FormData(); files.forEach(file => body.append("files", file)); setResult(await request("/api/data/import/batch", { method: "POST", body })); await symbols.refetch(); };
  const fetchEtfBasket = async () => {
    setFutuResult(null);
    setFutuResult(await request("/api/data/futu/snapshots/batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes: ["US.SPY", "US.QQQ", "US.IWM", "US.XLF", "US.XLE", "US.XLV", "US.XLI", "US.XLU"], timeframe: "1d", autype: "QFQ", start: "2010-01-01" }) }));
    await futuCoverage.refetch();
  };
  const eligible = coverage.data?.eligible_symbols ?? 0;
  const futuEligible = futuCoverage.data?.eligible_symbols ?? 0;
  return <div className="terminal-page pt-0">
    <section className="panel p-4"><div className="panel-title">批量导入 CSV</div><p className="muted">本地 OHLCV 研究数据；文件名即证券代码，字段固定为 date、open、high、low、close、volume。</p><div className="mt-3 flex gap-2"><input className="terminal-input" type="file" multiple accept=".csv" onChange={e => setFiles(Array.from(e.target.files ?? []))}/><button className="primary-button" disabled={!files.length} onClick={() => void upload()}>导入 {files.length || ""} 个文件</button></div>{result && <div className="mt-3 text-sm">已导入 {result.imported} · 未变化 {result.unchanged} · 已拒绝 {result.rejected}<table className="mt-2"><tbody>{result.results.map((x: any) => <tr key={x.filename}><td>{x.symbol}</td><td>{x.status}</td><td>{x.bars ?? "—"}</td><td>{x.warnings?.join("; ")}</td></tr>)}</tbody></table></div>}</section>
    <section className={futuCoverage.data?.status === "READY" ? "success-banner mt-4" : "error-banner mt-4"}><b>OpenD ETF 验证数据：{futuEligible} / {futuCoverage.data?.required_symbols ?? 8} 个合格标的</b><p className="mt-1">不可变日线前复权快照：SPY、QQQ、IWM、XLF、XLE、XLV、XLI、XLU。750 根日线以下仍可运行，但仅作探索性样本。</p><div className="mt-3 flex gap-3 items-center"><button className="primary-button" disabled={futuCoverage.isFetching} onClick={() => void fetchEtfBasket()}>{futuCoverage.isFetching ? "正在读取快照…" : "拉取 8 个 ETF 日线快照"}</button>{futuResult && <span className="text-sm muted">本次完成 {futuResult.created?.length ?? 0} 个，失败 {futuResult.failed?.length ?? 0} 个；不会覆盖已有快照。</span>}</div></section>
    <section className="panel mt-4 overflow-hidden"><div className="p-4 panel-title">OpenD ETF 快照覆盖</div><table><thead><tr><th>标的</th><th>快照</th><th>K线数量</th><th>日期覆盖</th><th>新鲜度</th><th>研究资格</th></tr></thead><tbody>{futuCoverage.data?.symbols.map(row => <tr key={row.code}><td>{row.symbol}</td><td>{row.snapshot_id ? row.snapshot_id.slice(0, 12) : "—"}</td><td>{row.bars}</td><td>{row.start_date && row.end_date ? `${row.start_date} ~ ${row.end_date}` : "—"}</td><td>{row.freshness}</td><td>{row.research_eligibility}</td></tr>)}</tbody></table></section>
    <section className={coverage.data?.status === "READY" ? "success-banner mt-4" : "error-banner mt-4"}><b>本地 CSV 多资产验证：{eligible} / {coverage.data?.required_symbols ?? 8} 个合格标的 · 代表性篮子 {coverage.data?.basket_coverage ?? 0} / 8</b><p className="mt-1">本地 CSV 是独立研究来源；未达到标准前，结果只能作为探索性研究。</p><div className="mt-2 flex flex-wrap gap-2">{coverage.data?.basket.map(item => <span key={item.symbol} className={item.eligible ? "border border-emerald-800 px-2 py-1 text-xs text-emerald-300" : "border border-zinc-700 px-2 py-1 text-xs text-zinc-400"}>{item.symbol} · {item.category}</span>)}</div></section>
    <section className="panel mt-4 overflow-hidden"><div className="p-4 panel-title">本地研究标的池</div><table><thead><tr><th>证券代码</th><th>K线数量</th><th>开始日期</th><th>结束日期</th><th>数据新鲜度</th><th>研究资格</th></tr></thead><tbody>{symbols.data?.symbols.map(row => <tr key={row.symbol}><td>{row.symbol}</td><td>{row.bars}</td><td>{row.start_date}</td><td>{row.end_date}</td><td>{row.freshness}</td><td>{row.research_eligibility}</td></tr>)}</tbody></table></section>
  </div>;
}
