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
    const body = await request.json();

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
    const body = await request.json();

    // Simulate updating strategy
    return HttpResponse.json({
      success: true,
      message: `Strategy ${id} updated`,
    });
  }),

  // Dashboard endpoints
  http.get('/api/metrics/summary', ({ request }) => {
    const url = new URL(request.url);
    // Parse query parameters if needed
    const from = url.searchParams.get('from');
    const to = url.searchParams.get('to');

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

  // Backtest endpoints
  http.post('/api/backtests', async ({ request }) => {
    const body = await request.json();

    // Simulate starting backtest
    return HttpResponse.json({
      jobId: `backtest-${Date.now()}`,
      status: 'queued',
    });
  }),

  http.get('/api/backtests/:jobId', ({ params }) => {
    const { jobId } = params;

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
