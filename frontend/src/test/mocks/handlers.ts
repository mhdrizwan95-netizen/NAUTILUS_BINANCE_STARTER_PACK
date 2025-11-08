import { http, HttpResponse } from 'msw';

// Mock data generators
const generateMockStrategies = () => [
  {
    id: 'hmm',
    name: 'HMM',
    kind: 'HMM',
    status: 'running' as const,
    symbols: ['BTC/USDT', 'ETH/USDT'],
    paramsSchema: { fields: [] },
    performance: {
      pnl: 1250.50,
      equitySeries: [
        { t: '2025-01-01', equity: 10000 },
        { t: '2025-01-02', equity: 10150 },
      ],
      winRate: 0.68,
      sharpe: 1.8,
      drawdown: 0.05,
    },
  },
  {
    id: 'meanrev',
    name: 'MeanRev',
    kind: 'MeanRev',
    status: 'stopped' as const,
    symbols: ['AAPL', 'TSLA'],
    paramsSchema: { fields: [] },
    performance: {
      pnl: -320.25,
      equitySeries: [
        { t: '2025-01-01', equity: 10000 },
        { t: '2025-01-02', equity: 9680 },
      ],
      winRate: 0.45,
      sharpe: 0.3,
      drawdown: 0.12,
    },
  },
];

const generateMockDashboardSummary = () => ({
  kpis: {
    totalPnl: 1847.25,
    winRate: 0.62,
    sharpe: 1.45,
    maxDrawdown: 0.08,
    openPositions: 12,
  },
  equityByStrategy: [
    { t: '2025-01-01', HMM: 10000, MeanRev: 10000 },
    { t: '2025-01-02', HMM: 11250, MeanRev: 9680 },
  ],
  pnlBySymbol: [
    { symbol: 'BTC/USDT', pnl: 1250.50 },
    { symbol: 'ETH/USDT', pnl: 596.75 },
    { symbol: 'AAPL', pnl: -320.25 },
  ],
  returns: [0.02, -0.03, 0.015, 0.008, -0.005],
});

const generateMockPositions = () => [
  {
    symbol: 'BTC/USDT',
    qty: 0.5,
    entry: 45000,
    mark: 46500,
    pnl: 750,
  },
  {
    symbol: 'ETH/USDT',
    qty: 5,
    entry: 2800,
    mark: 2950,
    pnl: 750,
  },
];

const generateMockTrades = () => [
  {
    id: 'trade-1',
    timestamp: Date.now() - 300000,
    symbol: 'BTC/USDT',
    side: 'buy' as const,
    quantity: 0.5,
    price: 45000,
    pnl: 750,
    strategyId: 'hmm',
    venueId: 'binance',
  },
  {
    id: 'trade-2',
    timestamp: Date.now() - 600000,
    symbol: 'ETH/USDT',
    side: 'sell' as const,
    quantity: 2,
    price: 2900,
    pnl: -200,
    strategyId: 'meanrev',
    venueId: 'bybit',
  },
];

const generateMockAlerts = () => [
  {
    id: 'alert-1',
    timestamp: Date.now() - 120000,
    type: 'warning' as const,
    message: 'High volatility detected on BTC/USDT',
    strategyId: 'hmm',
  },
  {
    id: 'alert-2',
    timestamp: Date.now() - 300000,
    type: 'info' as const,
    message: 'Strategy HMM performance above threshold',
  },
];

const generateMockHealth = () => ({
  venues: [
    {
      name: 'Binance',
      status: 'ok' as const,
      latencyMs: 45,
      queue: 2,
    },
    {
      name: 'Bybit',
      status: 'ok' as const,
      latencyMs: 52,
      queue: 1,
    },
  ],
});

const mockPortfolioAggregate = () => ({
  equity_usd: 425000,
  cash_usd: 175000,
  gain_usd: 12500,
  return_pct: 0.032,
  baseline_equity_usd: 412500,
  last_refresh_epoch: Math.floor(Date.now() / 1000),
});

const mockExposureAggregate = () => ({
  totals: {
    exposure_usd: 250000,
    count: 5,
    venues: 2,
  },
  by_symbol: {
    'BTCUSDT.BINANCE': {
      qty_base: 1.25,
      last_price_usd: 59000,
      exposure_usd: 73750,
    },
    'ETHUSDT.BINANCE': {
      qty_base: 10,
      last_price_usd: 3200,
      exposure_usd: 32000,
    },
    'AAPL.IBKR': {
      qty_base: 120,
      last_price_usd: 170,
      exposure_usd: 20400,
    },
  },
});

const mockPnlSnapshot = () => ({
  realized: {
    BINANCE: 6800,
    IBKR: 2200,
  },
  unrealized: {
    BINANCE: 5400,
    IBKR: -800,
  },
});

const mockConfigEffective = () => ({
  base: {
    demo_mode: false,
  },
  overrides: {
    DRY_RUN: false,
    SYMBOL_SCANNER_ENABLED: true,
    SOFT_BREACH_ENABLED: true,
    SOFT_BREACH_TIGHTEN_SL_PCT: 0.12,
    SOFT_BREACH_BREAKEVEN_OK: true,
    SOFT_BREACH_CANCEL_ENTRIES: false,
  },
  effective: {
    demo_mode: false,
    DRY_RUN: false,
    SYMBOL_SCANNER_ENABLED: true,
    SOFT_BREACH_ENABLED: true,
    SOFT_BREACH_TIGHTEN_SL_PCT: 0.12,
    SOFT_BREACH_BREAKEVEN_OK: true,
    SOFT_BREACH_CANCEL_ENTRIES: false,
  },
});

// HTTP request handlers
export const handlers = [
  // Strategies endpoints
  http.get('/api/strategies', () => {
    return HttpResponse.json(generateMockStrategies());
  }),

  http.get('/api/strategies/:id', ({ params }) => {
    const { id } = params;
    const strategies = generateMockStrategies();
    const strategy = strategies.find(s => s.id === id);

    if (!strategy) {
      return new HttpResponse(null, { status: 404 });
    }

    return HttpResponse.json(strategy);
  }),

  http.post('/api/strategies/:id/start', async ({ params, request }) => {
    const { id } = params;
    await request.json();

    // Simulate starting strategy
    return HttpResponse.json({
      success: true,
      message: `Strategy ${id} started`,
    });
  }),

  http.post('/api/strategies/:id/stop', ({ params }) => {
    const { id } = params;

    // Simulate stopping strategy
    return HttpResponse.json({
      success: true,
      message: `Strategy ${id} stopped`,
    });
  }),

  http.post('/api/strategies/:id/update', async ({ params, request }) => {
    const { id } = params;
    await request.json();

    // Simulate updating strategy
    return HttpResponse.json({
      success: true,
      message: `Strategy ${id} updated`,
    });
  }),

  // Dashboard endpoints
  http.get('/api/metrics/summary', ({ request }) => {
    const url = new URL(request.url);
    url.searchParams.toString(); // Parsed for parity with real handler
    return HttpResponse.json(generateMockDashboardSummary());
  }),

  http.get('/api/positions', () => {
    return HttpResponse.json(generateMockPositions());
  }),

  http.get('/api/trades/recent', () => {
    return HttpResponse.json(generateMockTrades());
  }),

  http.get('/api/alerts', () => {
    return HttpResponse.json(generateMockAlerts());
  }),

  http.get('/api/health', () => {
    return HttpResponse.json(generateMockHealth());
  }),

  http.get('/aggregate/portfolio', () => {
    return HttpResponse.json(mockPortfolioAggregate());
  }),

  http.get('/aggregate/exposure', () => {
    return HttpResponse.json(mockExposureAggregate());
  }),

  http.get('/aggregate/pnl', () => {
    return HttpResponse.json(mockPnlSnapshot());
  }),

  http.get('/api/config/effective', () => {
    return HttpResponse.json(mockConfigEffective());
  }),

  // Backtest endpoints
  http.post('/api/backtests', async ({ request }) => {
    await request.json();

    // Simulate starting backtest
    return HttpResponse.json({
      jobId: `backtest-${Date.now()}`,
      status: 'queued',
    });
  }),

  http.get('/api/backtests/:jobId', () => {
    // Simulate backtest progress
    return HttpResponse.json({
      status: 'completed',
      progress: 100,
      result: {
        metrics: {
          totalReturn: 0.15,
          sharpe: 1.8,
          maxDrawdown: 0.08,
          winRate: 0.65,
          trades: 45,
        },
        equityCurve: [
          { t: '2025-01-01', equity: 10000 },
          { t: '2025-01-31', equity: 11500 },
        ],
        pnlBySymbol: [
          { symbol: 'BTC/USDT', pnl: 1200 },
          { symbol: 'ETH/USDT', pnl: 300 },
        ],
        returns: [0.02, 0.015, -0.01, 0.03, 0.008],
        trades: [
          {
            time: '2025-01-15T10:30:00Z',
            symbol: 'BTC/USDT',
            side: 'buy' as const,
            qty: 0.5,
            price: 45000,
            pnl: 800,
          },
        ],
      },
    });
  }),
];
