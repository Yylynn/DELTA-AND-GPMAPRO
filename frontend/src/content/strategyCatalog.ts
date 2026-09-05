import type { ChartLayer } from "@/components/TerminalChart";

export type StrategyAvailability = "READY" | "PENDING_ADAPTATION";
export type StrategyCategory = "当前终端" | "股票" | "期货" | "期权";

export type StrategyCatalogEntry = {
  id: string;
  name: string;
  category: StrategyCategory;
  group: string;
  marketScope: string;
  availability: StrategyAvailability;
  version: string;
  source: { repository: string; path: string };
  adaptationNote: string;
  workspaceLayer?: ChartLayer;
};

const sourceRepository = "suenzyoung-cpu/financial_terminal@76fccb96";
const sourcePath = "backend/backtest/web/templates.py";
const pending = (
  id: string,
  name: string,
  category: Exclude<StrategyCategory, "当前终端">,
  path: string,
  group: string = category,
): StrategyCatalogEntry => ({
  id,
  name,
  category,
  group,
  marketScope: category === "期货" ? "期货（来源仓库）" : category === "期权" ? "期权（来源仓库）" : "股票 / ETF（来源仓库）",
  availability: "PENDING_ADAPTATION",
  version: "来源实现待适配",
  source: { repository: sourceRepository, path },
  adaptationNote: "该策略已在来源仓库目录中登记；当前 DELTA 终端没有对应运行器，因此不能在此页面执行、生成信号或进入回测。",
});

const optionPath = "backend/backtest/options_backtest/strategies/__init__.py";

/** READY entries only point to functions already implemented in this terminal. */
export const strategyCatalog: readonly StrategyCatalogEntry[] = [
  {
    id: "delta", name: "DELTA", category: "当前终端", group: "当前终端", marketScope: "美股", availability: "READY", version: "当前终端 DELTA 图层",
    source: { repository: "DELTA-Time-Space", path: "backend/app/quant/delta_time.py" },
    adaptationNote: "打开总览工作台并激活 DELTA 图层；使用当前终端的研究快照和既有计算链路。", workspaceLayer: "delta",
  },
  {
    id: "gpmapro", name: "GPMAPRO", category: "当前终端", group: "当前终端", marketScope: "美股", availability: "READY", version: "GPMAPRO",
    source: { repository: "DELTA-Time-Space", path: "backend/app/services/gpmapro_engine.py" },
    adaptationNote: "打开总览工作台并激活 GPMAPRO 图层；不自动生成交易指令或回测。", workspaceLayer: "gpmapro",
  },
  {
    id: "gpma2", name: "GPMA2", category: "当前终端", group: "当前终端", marketScope: "美股", availability: "READY", version: "GPMAPRO 第二版本（GPMA2）",
    source: { repository: "DELTA-Time-Space", path: "backend/app/api/gpma2.py" },
    adaptationNote: "打开总览工作台并激活 GPMA2 图层；它沿用同一份研究快照。", workspaceLayer: "gpma2",
  },
  {
    id: "chanlun", name: "简化缠论", category: "当前终端", group: "当前终端", marketScope: "美股日线", availability: "READY", version: "financial_terminal 简化算法移植版",
    source: { repository: sourceRepository, path: "backend/common/chanlun.py" },
    adaptationNote: "打开日线总览工作台并激活缠论图层；展示包含关系、分型、笔、中枢和简化买卖点，供研究查看。", workspaceLayer: "chanlun",
  },
  pending("ma-cross", "双均线趋势跟踪", "股票", sourcePath),
  pending("macd", "MACD 金叉死叉", "股票", sourcePath),
  pending("bollinger", "布林带均值回归", "股票", sourcePath),
  pending("turtle", "海龟交易法则", "股票", sourcePath),
  pending("momentum", "动量轮动", "股票", sourcePath),
  pending("rsi", "RSI 超买超卖", "股票", sourcePath),
  pending("futures-rule", "规则类回测", "期货", "backend/backtest/futures_backtest"),
  pending("futures-factor", "因子类回测", "期货", "backend/backtest/futures_backtest"),
  ...[["long-call", "Long Call"], ["long-put", "Long Put"], ["short-call", "Short Call"], ["short-put", "Short Put"]].map(([id, name]) => pending(id, name, "期权", optionPath, "单腿")),
  ...[["covered-call", "Covered Call"], ["covered-put", "Covered Put"], ["protective-put", "Protective Put"], ["protective-call", "Protective Call"], ["collar", "Collar"]].map(([id, name]) => pending(id, name, "期权", optionPath, "备兑保护")),
  ...[["bull-call-spread", "Bull Call Spread"], ["bear-call-spread", "Bear Call Spread"], ["bull-put-spread", "Bull Put Spread"], ["bear-put-spread", "Bear Put Spread"]].map(([id, name]) => pending(id, name, "期权", optionPath, "方向价差")),
  ...[["long-straddle", "Long Straddle"], ["short-straddle", "Short Straddle"], ["long-strangle", "Long Strangle"], ["short-strangle", "Short Strangle"]].map(([id, name]) => pending(id, name, "期权", optionPath, "跨式宽跨式")),
  ...[["call-butterfly", "Call Butterfly"], ["put-butterfly", "Put Butterfly"], ["iron-butterfly", "Iron Butterfly"], ["reverse-iron-butterfly", "Reverse Iron Butterfly"], ["call-condor", "Call Condor"], ["put-condor", "Put Condor"], ["iron-condor", "Iron Condor"], ["reverse-iron-condor", "Reverse Iron Condor"]].map(([id, name]) => pending(id, name, "期权", optionPath, "蝶式鹰式")),
  ...[["long-calendar", "Long Calendar Spread"], ["short-calendar", "Short Calendar Spread"], ["diagonal", "Diagonal Spread"], ["double-diagonal", "Double Diagonal Spread"]].map(([id, name]) => pending(id, name, "期权", optionPath, "日历对角")),
  ...[["call-ratio", "Call Ratio Spread"], ["put-ratio", "Put Ratio Spread"], ["call-backspread", "Call Backspread"], ["put-backspread", "Put Backspread"], ["christmas-tree", "Christmas Tree Spread"], ["box-spread", "Box Spread"], ["conversion", "Conversion"], ["reversal", "Reversal"], ["synthetic-long", "Synthetic Long Stock"], ["synthetic-short", "Synthetic Short Stock"]].map(([id, name]) => pending(id, name, "期权", optionPath, "比率组合")),
  ...[["buy-write", "Buy Write"], ["put-write", "Put Write"], ["tail-risk", "Tail Risk Hedging"], ["gamma-scalp", "Gamma Scalp"], ["var-swap", "Var Swap Proxy"]].map(([id, name]) => pending(id, name, "期权", optionPath, "特殊场景")),
];
