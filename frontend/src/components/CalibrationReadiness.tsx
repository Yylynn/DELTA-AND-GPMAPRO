import { useQuery } from "@tanstack/react-query";

const request = async (path: string) => { const response = await fetch(path); if (!response.ok) throw new Error(await response.text()); return response.json(); };

export function CalibrationReadiness() {
  const etfs = useQuery<any>({ queryKey: ["strategy-lab-etf-readiness"], queryFn: () => request("/api/data/futu/research-coverage"), retry: false });
  const legacy = useQuery<any>({ queryKey: ["legacy-calibration-readiness"], queryFn: () => request("/api/diagnostics/readiness"), retry: false });
  const ready = etfs.data?.status === "READY";
  return <section className={`panel panel-research readiness-panel mb-4 p-4 ${ready ? "is-ready" : "is-blocked"}`}><div className="toolbar"><div><div className="panel-title">策略实验数据准备度</div><p className="muted">OpenD ETF 快照是本阶段的验证口径；它不会调整任何买卖规则。</p></div><b className={ready ? "text-emerald-300" : "text-amber-300"}>{ready ? "ETF 验证就绪" : "ETF 数据待补"}</b></div><div className="grid grid-cols-3 gap-3 text-sm"><div className="readiness-step"><span>合格 ETF（日线 ≥ 750）</span><b>{etfs.data?.eligible_symbols ?? 0} / {etfs.data?.required_symbols ?? 8} · {ready ? "已满足" : "待补足"}</b></div><div className="readiness-step"><span>快照来源</span><b>OpenD · 日线前复权 · 不可变</b></div><div className="readiness-step"><span>旧本地 CSV 校准</span><b>{legacy.data?.status === "READY_FOR_CALIBRATION" ? "已满足" : "不作为本阶段门槛"}</b></div></div></section>;
}
