import { ArrowLeft } from "lucide-react";
import { BacktestResultPanel } from "@/components/BacktestResultPanel";
import type { BacktestResult } from "@/components/backtestResultTypes";

export function BacktestResultWorkspace({
  result,
  onBack,
}: {
  result: BacktestResult;
  onBack: () => void;
}) {
  return (
    <div className="grid gap-4">
      <section className="panel backtest-result-shell">
        <div className="backtest-result-frame">
          <button
            type="button"
            className="secondary-button inline-flex items-center gap-2"
            onClick={onBack}
          >
            <ArrowLeft size={14} /> 返回数据、K 线与规则
          </button>
          <BacktestResultPanel result={result} stale={false} />
        </div>
      </section>
    </div>
  );
}
