export type BacktestDataset = {
  dataset_id: string;
  symbol: string;
  start_date: string;
  end_date: string;
  source?: string;
  timeframe?: string;
  bar_count?: number;
  adjustment?: string;
  data_sha256?: string | null;
};

export type BacktestParameters = {
  buy_signals: string[];
  sell_signals: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  commission_bps_per_side: number;
  slippage_bps_per_side: number;
  max_holding_bars: number;
};

export type BacktestRunRequest = BacktestParameters & {
  dataset_id: string;
};

export type BacktestMetrics = {
  total_return: number;
  annualized_return: number | null;
  max_drawdown: number;
  annualized_volatility: number | null;
  sharpe: number | null;
  trade_count: number;
  win_rate: number | null;
  average_trade_return: number | null;
  profit_factor: number | null;
  exposure_rate: number;
};

export type BacktestTrade = {
  symbol: string;
  entry_signal_date: string;
  entry_date: string;
  exit_signal_date: string | null;
  exit_date: string;
  entry_signals: string[];
  exit_signals: string[];
  entry_price: number;
  exit_price: number;
  shares: number;
  gross_return: number;
  net_return: number;
  pnl: number;
  cost_amount: number;
  holding_bars: number;
  mfe: number;
  mae: number;
  exit_reason: "SELL_SIGNAL" | "MAX_HOLD";
};

export type BacktestResult = {
  dataset: BacktestDataset;
  parameters: BacktestParameters;
  period: { start: string; end: string; bar_count: number };
  run_fingerprint: string;
  metrics: BacktestMetrics;
  benchmark_metrics: BacktestMetrics;
  equity_curve: Array<{ date: string; equity: number; cash: number; in_position: boolean }>;
  benchmark_curve: Array<{ date: string; equity: number }>;
  drawdown_curve: Array<{
    date: string;
    strategy_drawdown: number;
    benchmark_drawdown: number;
  }>;
  monthly_returns: Array<{
    month: string;
    strategy_return: number;
    benchmark_return: number;
    excess_return: number;
  }>;
  closed_trades: BacktestTrade[];
  trade_analysis: {
    best_trade: BacktestTrade | null;
    worst_trade: BacktestTrade | null;
    average_holding_bars: number | null;
    average_win: number | null;
    average_loss: number | null;
    payoff_ratio: number | null;
    max_consecutive_losses: number;
    exit_reason_counts: Record<string, number>;
  };
  open_position: null | {
    entry_signal_date: string;
    entry_date: string;
    entry_signals: string[];
    entry_price: number;
    shares: number;
    last_date: string;
    last_close: number;
    unrealized_return: number;
    unrealized_pnl: number;
  };
  signal_counts: Record<string, number>;
  assumptions: Record<string, string>;
};
