export const BACKTEST_SIGNAL_LABELS: Record<string, string> = {
  BOTTOM_FACE: "底部一级笑脸 ☺",
  TOP_FACE: "顶部一级哭脸 ☹",
  BOTTOM_ARROW_2: "底部二级箭头 ↑",
  TOP_ARROW_2: "顶部二级箭头 ↓",
};

export const backtestSignalLabel = (code: string) =>
  BACKTEST_SIGNAL_LABELS[code] ?? code.replace("DELTA_", "DELTA ");
