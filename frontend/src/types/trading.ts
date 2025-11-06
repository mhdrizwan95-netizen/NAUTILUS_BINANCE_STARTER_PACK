import type { ParamSchema } from './settings';

// Trading domain types
export type VenueType = 'crypto' | 'equities' | 'fx';
export type MarketType = 'spot' | 'futures' | 'options';
export type StrategyType = 'HMM' | 'MeanRev' | 'Breakout' | 'Scalp' | 'Momentum' | 'Meme' | 'Listing' | 'VolScan';
export type ModeType = 'paper' | 'live';

export interface Venue {
  id: string;
  name: string;
  type: VenueType;
  status: 'connected' | 'degraded' | 'offline';
  latency: number;
}

export interface Strategy {
  id: string;
  name: StrategyType;
  enabled: boolean;
  capital: number;
  markets: MarketType[];
}

export interface PerformanceMetrics {
  pnl: number;
  pnlPercent: number;
  sharpe: number;
  var: number;
  drawdown: number;
  tradeCount: number;
  winRate: number;
  latency: number;
  topSymbols: Array<{ symbol: string; pnl: number }>;
  sparkline: number[];
}

export interface StrategyPerformance {
  strategyId: string;
  venueId: string;
  metrics: PerformanceMetrics;
  health: 'optimal' | 'warning' | 'critical';
}

export interface Trade {
  id: string;
  timestamp: number;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  pnl?: number;
  strategyId: string;
  venueId: string;
}

export interface Alert {
  id: string;
  timestamp: number;
  type: 'info' | 'warning' | 'error';
  message: string;
  strategyId?: string;
}

export interface Order {
  id: string;
  symbol: string;
  side: string;
  type: string;
  qty: number;
  filled: number;
  price: number;
  status: string;
  createdAt: number;
}

export interface MetricsModel {
  id: string;
  model: string;
  venue: string;
  ordersSubmitted: number;
  ordersFilled: number;
  trades: number;
  pnlRealized: number;
  pnlUnrealized: number;
  totalPnl: number;
  winRate: number;
  returnPct: number;
  sharpe: number;
  drawdown: number;
  maxDrawdown: number;
  strategyType?: string | null;
  version?: string | null;
  tradingDays?: number | null;
}

export interface GlobalMetrics {
  totalPnL: number;
  totalPnLPercent: number;
  sharpe: number;
  drawdown: number;
  activePositions: number;
  dailyTradeCount: number;
}

// Schema-driven UI data contracts
export type KPI = { label: string; value: string | number; hint?: string };

export type EquityPoint = { t: string; equity: number };
export type Series<T> = Array<T>;

export type StrategyPerformanceSnapshot = {
  pnl: number;
  equitySeries?: Series<EquityPoint>;
  winRate?: number;
  sharpe?: number;
  drawdown?: number;
};

export type StrategySummary = {
  id: string;
  name: string;
  kind: string;
  status: 'stopped' | 'running' | 'error';
  symbols: string[];
  paramsSchema: ParamSchema;
  params?: Record<string, unknown>;
  performance?: StrategyPerformanceSnapshot;
};

export type BacktestResult = {
  metrics: {
    totalReturn: number;
    sharpe: number;
    maxDrawdown: number;
    winRate: number;
    trades: number;
  };
  equityCurve: Series<EquityPoint>;
  pnlBySymbol: Array<{ symbol: string; pnl: number }>;
  returns: number[];
  trades?: Array<{
    time: string;
    symbol: string;
    side: 'buy' | 'sell';
    qty: number;
    price: number;
    pnl?: number;
  }>;
};

export type PortfolioAggregate = {
  equity_usd: number;
  cash_usd: number;
  gain_usd: number;
  return_pct: number;
  baseline_equity_usd: number;
  last_refresh_epoch?: number | null;
};

export type ExposureEntry = {
  qty_base: number;
  last_price_usd: number;
  exposure_usd: number;
};

export type ExposureAggregate = {
  totals: {
    exposure_usd: number;
    count: number;
    venues: number;
  };
  by_symbol: Record<string, ExposureEntry>;
};

export type PnlSnapshot = {
  realized: Record<string, number>;
  unrealized: Record<string, number>;
};
