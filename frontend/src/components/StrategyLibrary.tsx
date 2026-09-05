import { useMemo, useState } from "react";
import { BookOpen, ExternalLink, Play, Search } from "lucide-react";
import {
  strategyCatalog,
  type StrategyAvailability,
  type StrategyCategory,
  type StrategyCatalogEntry,
} from "@/content/strategyCatalog";
import { PageHeader, StatusBadge } from "@/components/ui/workspace";
import type { ChartLayer } from "@/components/TerminalChart";

const statusLabels: Record<StrategyAvailability, string> = {
  READY: "可打开工作台",
  PENDING_ADAPTATION: "待适配",
};

function statusTone(status: StrategyAvailability): "warning" | "positive" {
  return status === "READY" ? "positive" : "warning";
}

function normalizeUsCode(value: string) {
  const code = value.trim().toUpperCase();
  return code.startsWith("US.") ? code : `US.${code}`;
}

function StrategyDetail({ strategy, onOpenWorkspace }: { strategy: StrategyCatalogEntry; onOpenWorkspace: (code: string, layer: ChartLayer) => void }) {
  const [symbol, setSymbol] = useState("AAPL");
  const ready = strategy.availability === "READY" && strategy.workspaceLayer;

  return (
    <section className="strategy-library-detail panel" aria-live="polite">
      <div className="strategy-library-detail-heading">
        <div>
          <span>STRATEGY REFERENCE</span>
          <h2>{strategy.name}</h2>
        </div>
        <StatusBadge tone={statusTone(strategy.availability)}>{statusLabels[strategy.availability]}</StatusBadge>
      </div>
      <dl className="strategy-library-facts">
        <div><dt>资料范围</dt><dd>{strategy.marketScope}</dd></div>
        <div><dt>版本 / 适配状态</dt><dd>{strategy.version}</dd></div>
        <div><dt>来源定位</dt><dd>{strategy.source.repository}<br />{strategy.source.path}</dd></div>
      </dl>
      <article className={`strategy-library-pending ${ready ? "is-ready" : ""}`}>
        {ready ? <Play size={18} aria-hidden="true" /> : <BookOpen size={18} aria-hidden="true" />}
        <div>
          <strong>{ready ? "可在当前终端中使用" : "等待终端适配"}</strong>
          <p>{strategy.adaptationNote}</p>
        </div>
      </article>
      {ready ? (
        <form className="strategy-library-open-form" onSubmit={(event) => {
          event.preventDefault();
          if (symbol.trim()) onOpenWorkspace(normalizeUsCode(symbol), strategy.workspaceLayer!);
        }}>
          <label>
            <span>美股代码</span>
            <input value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="AAPL" aria-label="美股代码" />
          </label>
          <button className="primary-button" type="submit"><Play size={15} /> 打开策略工作台</button>
        </form>
      ) : (
        <button className="secondary-button strategy-library-disabled" type="button" disabled><ExternalLink size={15} /> 当前终端尚无运行器</button>
      )}
      <p className="strategy-library-boundary">
        研究用途，不构成投资建议；不连接账户、不下单、不自动进入回测。需要评估策略表现时，请单独前往“回测实验室”。
      </p>
    </section>
  );
}

export function StrategyLibrary({ onOpenWorkspace }: { onOpenWorkspace: (code: string, layer: ChartLayer) => void }) {
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | StrategyAvailability>("ALL");
  const [categoryFilter, setCategoryFilter] = useState<"ALL" | StrategyCategory>("ALL");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const visibleStrategies = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return strategyCatalog.filter((strategy) => {
      const matchesKeyword = !needle || `${strategy.name} ${strategy.marketScope} ${strategy.category}`.toLowerCase().includes(needle);
      return matchesKeyword && (statusFilter === "ALL" || strategy.availability === statusFilter) && (categoryFilter === "ALL" || strategy.category === categoryFilter);
    });
  }, [keyword, statusFilter, categoryFilter]);
  const selected = strategyCatalog.find((strategy) => strategy.id === selectedId) ?? null;

  return (
    <div className="terminal-page strategy-library">
      <PageHeader
        title="交易策略集"
        description="可运行策略会进入同一份美股研究快照的总览工作台；来源策略在完成终端适配前仅供目录查看。"
      />
      <section className="strategy-library-notice" role="note">
        <BookOpen size={17} aria-hidden="true" />
        <span>研究用途，不构成投资建议；不连接账户、不下单，也不会自动进入回测。</span>
      </section>
      <section className="strategy-library-toolbar panel" aria-label="策略筛选">
        <label className="strategy-library-search">
          <Search size={16} aria-hidden="true" />
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索策略名称" />
        </label>
        <label>
          <span>资料状态</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "ALL" | StrategyAvailability)}>
            <option value="ALL">全部</option>
            {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          <span>分类</span>
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value as "ALL" | StrategyCategory)}>
            <option value="ALL">全部分类</option>
            {(["当前终端", "股票", "期货", "期权"] as const).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </section>
      <section className="strategy-library-grid" aria-label="策略目录">
        {visibleStrategies.map((strategy) => {
          const status = strategy.availability;
          return <article className={`strategy-library-card ${selected?.id === strategy.id ? "selected" : ""}`} key={strategy.id}>
            <div className="strategy-library-card-top">
              <span>{strategy.category} · {strategy.group} · {strategy.marketScope}</span>
              <StatusBadge tone={statusTone(status)}>{statusLabels[status]}</StatusBadge>
            </div>
            <h2>{strategy.name}</h2>
            <p>{strategy.adaptationNote}</p>
            <small>{strategy.version}</small>
            <button className={status === "READY" ? "primary-button" : "secondary-button"} onClick={() => setSelectedId(strategy.id)}>{status === "READY" ? "使用策略" : "查看适配说明"}</button>
          </article>;
        })}
      </section>
      {!visibleStrategies.length && <section className="strategy-library-empty panel"><strong>未找到策略</strong><span>请调整搜索词或资料状态。</span></section>}
      {selected && <StrategyDetail key={selected.id} strategy={selected} onOpenWorkspace={onOpenWorkspace} />}
    </div>
  );
}
