import { z } from 'zod';

// Trading mode validation
export const modeSchema = z.enum(['paper', 'live']);

// Venue status validation
export const venueStatusSchema = z.enum(['connected', 'degraded', 'offline']);

// Venue type validation
export const venueTypeSchema = z.enum(['crypto', 'equities', 'fx']);

// Strategy type validation
export const strategyTypeSchema = z.enum([
  'HMM', 'MeanRev', 'Breakout', 'Scalp', 'Momentum', 'Meme', 'Listing', 'VolScan'
]);

// Market type validation
export const marketTypeSchema = z.enum(['spot', 'futures', 'options']);

// Global metrics validation
export const globalMetricsSchema = z.object({
  totalPnL: z.number(),
  totalPnLPercent: z.number(),
  sharpe: z.number(),
  drawdown: z.number(),
  activePositions: z.number(),
  dailyTradeCount: z.number(),
});

// Venue validation
export const venueSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: venueTypeSchema,
  status: venueStatusSchema,
  latency: z.number().min(0),
});

// Strategy validation
export const strategySchema = z.object({
  id: z.string(),
  name: strategyTypeSchema,
  enabled: z.boolean(),
  capital: z.number().min(0),
  markets: z.array(marketTypeSchema),
});

// Performance metrics validation
export const performanceMetricsSchema = z.object({
  pnl: z.number(),
  pnlPercent: z.number(),
  sharpe: z.number(),
  var: z.number(),
  drawdown: z.number(),
  tradeCount: z.number().min(0),
  winRate: z.number().min(0).max(1),
  latency: z.number().min(0),
  topSymbols: z.array(z.object({
    symbol: z.string(),
    pnl: z.number(),
  })),
  sparkline: z.array(z.number()),
});

// Strategy performance validation
export const strategyPerformanceSchema = z.object({
  strategyId: z.string(),
  venueId: z.string(),
  metrics: performanceMetricsSchema,
  health: z.enum(['optimal', 'warning', 'critical']),
});

// Trade validation
export const tradeSchema = z.object({
  id: z.string(),
  timestamp: z.number(),
  symbol: z.string(),
  side: z.enum(['buy', 'sell']),
  quantity: z.number().positive(),
  price: z.number().positive(),
  pnl: z.number().optional(),
  strategyId: z.string(),
  venueId: z.string(),
});

// Alert validation
export const alertSchema = z.object({
  id: z.string(),
  timestamp: z.number(),
  type: z.enum(['info', 'warning', 'error']),
  message: z.string(),
  strategyId: z.string().optional(),
});

// Position validation
export const positionSchema = z.object({
  symbol: z.string(),
  qty: z.number(),
  entry: z.number().positive(),
  mark: z.number().positive(),
  pnl: z.number(),
});

// Dashboard summary validation
export const dashboardSummarySchema = z.object({
  kpis: z.object({
    totalPnl: z.number(),
    winRate: z.number().min(0).max(1),
    sharpe: z.number(),
    maxDrawdown: z.number().min(0).max(1),
    openPositions: z.number().min(0),
  }),
  equityByStrategy: z.array(z.record(z.string(), z.unknown())),
  pnlBySymbol: z.array(z.object({
    symbol: z.string(),
    pnl: z.number(),
  })),
  returns: z.array(z.number()),
});

export const portfolioAggregateSchema = z.object({
  equity_usd: z.number(),
  cash_usd: z.number(),
  gain_usd: z.number(),
  return_pct: z.number(),
  baseline_equity_usd: z.number(),
  last_refresh_epoch: z.number().nullable().optional(),
});

export const exposureEntrySchema = z.object({
  qty_base: z.number(),
  last_price_usd: z.number(),
  exposure_usd: z.number(),
});

export const exposureAggregateSchema = z.object({
  totals: z.object({
    exposure_usd: z.number(),
    count: z.number(),
    venues: z.number(),
  }),
  by_symbol: z.record(exposureEntrySchema),
});

export const pnlSnapshotSchema = z.object({
  realized: z.record(z.number()),
  unrealized: z.record(z.number()),
});

// Health check validation
export const healthCheckSchema = z.object({
  venues: z.array(z.object({
    name: z.string(),
    status: z.enum(['ok', 'warn', 'down']),
    latencyMs: z.number().min(0),
    queue: z.number().min(0),
  })),
});

// Strategy summary validation
export const strategySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  status: z.enum(['stopped', 'running', 'error']),
  symbols: z.array(z.string()),
  paramsSchema: z.any(), // Will be validated separately
  params: z.record(z.unknown()).optional(),
  performance: z.object({
    pnl: z.number(),
    equitySeries: z.array(z.object({
      t: z.string(),
      equity: z.number(),
    })).optional(),
    winRate: z.number().optional(),
    sharpe: z.number().optional(),
    drawdown: z.number().optional(),
  }).optional(),
});

export const configEffectiveSchema = z.object({
  base: z.record(z.unknown()),
  overrides: z.record(z.unknown()),
  effective: z.record(z.unknown()),
});

// Backtest result validation
export const backtestResultSchema = z.object({
  metrics: z.object({
    totalReturn: z.number(),
    sharpe: z.number(),
    maxDrawdown: z.number(),
    winRate: z.number(),
    trades: z.number(),
  }),
  equityCurve: z.array(z.object({
    t: z.string(),
    equity: z.number(),
  })),
  pnlBySymbol: z.array(z.object({
    symbol: z.string(),
    pnl: z.number(),
  })),
  returns: z.array(z.number()),
  trades: z.array(z.object({
    time: z.string(),
    symbol: z.string(),
    side: z.enum(['buy', 'sell']),
    qty: z.number(),
    price: z.number(),
    pnl: z.number().optional(),
  })).optional(),
});

// API request validation schemas

// Backtest start request
export const backtestStartSchema = z.object({
  strategyId: z.string(),
  params: z.record(z.unknown()).optional(),
  symbols: z.array(z.string()).optional(),
  startDate: z.string(),
  endDate: z.string(),
  initialCapital: z.number().positive().optional(),
  feeBps: z.number().min(0).optional(),
  slippageBps: z.number().min(0).optional(),
});

// Strategy update request
export const strategyUpdateSchema = z.object({
  params: z.record(z.unknown()),
});

// Form validation schemas

// Date range validation
export const dateRangeSchema = z.object({
  from: z.date(),
  to: z.date(),
}).refine((data) => data.from <= data.to, {
  message: "Start date must be before or equal to end date",
  path: ["from"],
});

// Filter parameters validation
export const dashboardFiltersSchema = z.object({
  dateRange: dateRangeSchema.optional(),
  strategies: z.array(z.string()).optional(),
  symbols: z.array(z.string()).optional(),
});

// User preferences validation
export const userPreferencesSchema = z.object({
  theme: z.enum(['light', 'dark', 'system']),
  autoRefresh: z.boolean(),
  refreshInterval: z.number().min(5).max(300), // 5 seconds to 5 minutes
  soundEnabled: z.boolean(),
  notificationsEnabled: z.boolean(),
});

// Utility functions for validation
export function validateApiResponse<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  context: string = 'API response'
): T {
  try {
    return schema.parse(data);
  } catch (error) {
    if (error instanceof z.ZodError) {
      console.error(`${context} validation failed:`, error.errors);
      throw new Error(`${context} validation failed: ${error.errors.map(e => e.message).join(', ')}`);
    }
    throw error;
  }
}

export function validateFormData<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  context: string = 'Form data'
): T {
  try {
    return schema.parse(data);
  } catch (error) {
    if (error instanceof z.ZodError) {
      // Return first error for form validation
      throw new Error(error.errors[0]?.message || `${context} validation failed`);
    }
    throw error;
  }
}

// Type exports for use in components
export type ModeType = z.infer<typeof modeSchema>;
export type VenueStatus = z.infer<typeof venueStatusSchema>;
export type VenueType = z.infer<typeof venueTypeSchema>;
export type StrategyType = z.infer<typeof strategyTypeSchema>;
export type MarketType = z.infer<typeof marketTypeSchema>;
export type GlobalMetrics = z.infer<typeof globalMetricsSchema>;
export type Venue = z.infer<typeof venueSchema>;
export type Strategy = z.infer<typeof strategySchema>;
export type PerformanceMetrics = z.infer<typeof performanceMetricsSchema>;
export type StrategyPerformance = z.infer<typeof strategyPerformanceSchema>;
export type Trade = z.infer<typeof tradeSchema>;
export type Alert = z.infer<typeof alertSchema>;
export type Position = z.infer<typeof positionSchema>;
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;
export type PortfolioAggregate = z.infer<typeof portfolioAggregateSchema>;
export type ExposureAggregate = z.infer<typeof exposureAggregateSchema>;
export type PnlSnapshot = z.infer<typeof pnlSnapshotSchema>;
export type HealthCheck = z.infer<typeof healthCheckSchema>;
export type StrategySummary = z.infer<typeof strategySummarySchema>;
export type BacktestResult = z.infer<typeof backtestResultSchema>;
export type BacktestStartRequest = z.infer<typeof backtestStartSchema>;
export type StrategyUpdateRequest = z.infer<typeof strategyUpdateSchema>;
export type ConfigEffective = z.infer<typeof configEffectiveSchema>;
export type DateRange = z.infer<typeof dateRangeSchema>;
export type DashboardFilters = z.infer<typeof dashboardFiltersSchema>;
export type UserPreferences = z.infer<typeof userPreferencesSchema>;
