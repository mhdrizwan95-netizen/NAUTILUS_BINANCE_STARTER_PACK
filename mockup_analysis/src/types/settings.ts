// Settings and configuration types

export interface GlobalSettings {
  leverageCap: number;
  perTradePercent: number;
  maxPositions: number;
  dailyLossStop: number;
  circuitBreakerEnabled: boolean;
  circuitBreakerThreshold: number;
}

export interface TrendStrategyConfig {
  maLength: number;
  rsiThreshold: number;
  cooldownMinutes: number;
  trailingStopPercent: number;
}

export interface ScalpStrategyConfig {
  spreadPercent: number;
  stopPercent: number;
  orderType: 'limit' | 'market';
  maxScalpsPerDay: number;
}

export interface MomentumStrategyConfig {
  surgePercent: number;
  trailingStopPercent: number;
  skipPumped: boolean;
  lookbackMinutes: number;
}

export interface MemeStrategyConfig {
  sentimentThreshold: number;
  twitterEnabled: boolean;
  redditEnabled: boolean;
  telegramEnabled: boolean;
  sizeCap: number;
}

export interface ListingStrategyConfig {
  autoBuy: boolean;
  maxSlippagePercent: number;
  takeProfitPercent: number;
  stopLossPercent: number;
}

export interface VolScannerConfig {
  spikePercent: number;
  mode: 'alert' | 'trade';
  minVolume: number;
}
