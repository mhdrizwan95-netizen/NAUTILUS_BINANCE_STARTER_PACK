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
  orderType: "limit" | "market";
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
  mode: "alert" | "trade";
  minVolume: number;
}

// Schema used to render dynamic parameter forms
export type ParamField =
  | {
      type: "number" | "integer";
      key: string;
      label: string;
      min?: number;
      max?: number;
      step?: number;
      default?: number;
      hint?: string;
    }
  | {
      type: "boolean";
      key: string;
      label: string;
      default?: boolean;
      hint?: string;
    }
  | {
      type: "string";
      key: string;
      label: string;
      placeholder?: string;
      default?: string;
      hint?: string;
    }
  | {
      type: "select";
      key: string;
      label: string;
      options: Array<{ value: string; label: string }>;
      default?: string;
      hint?: string;
    };

export type ParamSchema = {
  title?: string;
  fields: ReadonlyArray<ParamField>;
};
