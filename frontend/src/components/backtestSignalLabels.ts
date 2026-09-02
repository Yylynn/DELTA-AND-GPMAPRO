export const BACKTEST_SIGNAL_LABELS: Record<string, string> = {
  BOTTOM_FACE: "底部一级背离 ☺",
  TOP_FACE: "顶部一级背离 ☹",
  BOTTOM_ARROW_2: "底部二级背离 ↑",
  TOP_ARROW_2: "顶部二级背离 ↓",
  BOTTOM_ARROW_3: "底部三级背离 ⬆",
  TOP_ARROW_3: "顶部三级背离 ⬇",
};

const BACKTEST_DIVERGENCE_ICONS: Record<string, string> = {
  BOTTOM_FACE: "☺",
  TOP_FACE: "☹",
  BOTTOM_ARROW_2: "↑",
  TOP_ARROW_2: "↓",
  BOTTOM_ARROW_3: "⬆",
  TOP_ARROW_3: "⬇",
};

const versionedCode = (code: string) => {
  const match = /^V([12])_(.+)$/.exec(code);
  return match ? { version: match[1], signal: match[2] } : null;
};

export const backtestSignalShortLabel = (code: string) => {
  const parsed = versionedCode(code);
  const signal = parsed?.signal ?? code;
  return BACKTEST_SIGNAL_LABELS[signal] ?? signal;
};

export const backtestDivergenceIcon = (code: string) => {
  const parsed = versionedCode(code);
  return BACKTEST_DIVERGENCE_ICONS[parsed?.signal ?? code] ?? "";
};

export const backtestSignalLabel = (code: string) => {
  const parsed = versionedCode(code);
  const label = backtestSignalShortLabel(code);
  if (parsed && BACKTEST_SIGNAL_LABELS[parsed.signal]) return label;
  return parsed ? `${parsed.version === "1" ? "第一版" : "第二版"} · ${label}` : label;
};
