// Mock data generator for the trading terminal
import type {
  Venue,
  Strategy,
  StrategyPerformance,
  Trade,
  Alert,
  GlobalMetrics,
  VenueType,
} from "../types/trading";

export const venues: Venue[] = [
  { id: "binance", name: "Binance", type: "crypto", status: "connected", latency: 12 },
  { id: "bybit", name: "Bybit", type: "crypto", status: "connected", latency: 18 },
  { id: "ibkr", name: "IBKR", type: "equities", status: "connected", latency: 45 },
  { id: "oanda", name: "OANDA", type: "fx", status: "degraded", latency: 89 },
];

export const strategies: Strategy[] = [
  { id: "hmm", name: "HMM", enabled: true, capital: 50000, markets: ["spot", "futures"] },
  { id: "meanrev", name: "MeanRev", enabled: true, capital: 30000, markets: ["spot"] },
  { id: "breakout", name: "Breakout", enabled: true, capital: 40000, markets: ["futures"] },
  { id: "scalp", name: "Scalp", enabled: false, capital: 25000, markets: ["spot"] },
  { id: "momentum", name: "Momentum", enabled: true, capital: 35000, markets: ["spot", "futures"] },
  { id: "meme", name: "Meme", enabled: true, capital: 10000, markets: ["spot"] },
];

const generateSparkline = (trend: "up" | "down" | "volatile" | "flat" = "volatile"): number[] => {
  const points = 24;
  const data: number[] = [];
  let value = 100;

  for (let i = 0; i < points; i++) {
    if (trend === "up") {
      value += Math.random() * 3 - 0.5;
    } else if (trend === "down") {
      value -= Math.random() * 3 - 0.5;
    } else if (trend === "volatile") {
      value += Math.random() * 6 - 3;
    } else {
      value += Math.random() * 1 - 0.5;
    }
    data.push(value);
  }

  return data;
};

export const generatePerformanceData = (): StrategyPerformance[] => {
  const performances: StrategyPerformance[] = [];

  strategies.forEach((strategy) => {
    venues.forEach((venue) => {
      // Generate realistic performance based on strategy and venue compatibility
      const isCompatible =
        (venue.type === "crypto" && ["HMM", "Scalp", "Momentum", "Meme"].includes(strategy.name)) ||
        (venue.type === "equities" &&
          ["MeanRev", "Breakout", "Momentum"].includes(strategy.name)) ||
        (venue.type === "fx" && ["HMM", "MeanRev", "Breakout"].includes(strategy.name));

      if (!isCompatible || !strategy.enabled) return;

      const pnl = (Math.random() - 0.4) * 5000;
      const pnlPercent = (pnl / strategy.capital) * 100;

      performances.push({
        strategyId: strategy.id,
        venueId: venue.id,
        metrics: {
          pnl,
          pnlPercent,
          sharpe: Math.random() * 3 - 0.5,
          var: Math.random() * 0.03,
          drawdown: Math.random() * 0.15,
          tradeCount: Math.floor(Math.random() * 200),
          winRate: 0.45 + Math.random() * 0.2,
          latency: venue.latency + Math.random() * 10,
          topSymbols: [
            {
              symbol:
                venue.type === "crypto"
                  ? "BTC/USDT"
                  : venue.type === "equities"
                    ? "AAPL"
                    : "EUR/USD",
              pnl: Math.random() * 1000,
            },
            {
              symbol:
                venue.type === "crypto"
                  ? "ETH/USDT"
                  : venue.type === "equities"
                    ? "TSLA"
                    : "GBP/USD",
              pnl: Math.random() * 800,
            },
            {
              symbol:
                venue.type === "crypto"
                  ? "SOL/USDT"
                  : venue.type === "equities"
                    ? "NVDA"
                    : "USD/JPY",
              pnl: Math.random() * 600,
            },
          ],
          sparkline: generateSparkline(pnl > 0 ? "up" : pnl < -1000 ? "down" : "volatile"),
        },
        health: pnlPercent > 2 ? "optimal" : pnlPercent < -3 ? "critical" : "warning",
      });
    });
  });

  return performances;
};

export const generateRecentTrades = (count: number = 20): Trade[] => {
  const trades: Trade[] = [];
  const now = Date.now();

  for (let i = 0; i < count; i++) {
    const strategy = strategies[Math.floor(Math.random() * strategies.length)];
    const venue = venues[Math.floor(Math.random() * venues.length)];

    trades.push({
      id: `trade-${i}`,
      timestamp: now - i * 60000,
      symbol: venue.type === "crypto" ? "BTC/USDT" : venue.type === "equities" ? "AAPL" : "EUR/USD",
      side: Math.random() > 0.5 ? "buy" : "sell",
      quantity: Math.random() * 10,
      price: 50000 + Math.random() * 1000,
      pnl: (Math.random() - 0.5) * 200,
      strategyId: strategy.id,
      venueId: venue.id,
    });
  }

  return trades.sort((a, b) => b.timestamp - a.timestamp);
};

export const generateAlerts = (count: number = 10): Alert[] => {
  const alerts: Alert[] = [];
  const now = Date.now();

  const messages = [
    { type: "info" as const, msg: "New volume spike detected on BTC/USDT" },
    { type: "warning" as const, msg: "Latency increased on OANDA connection" },
    { type: "error" as const, msg: "Order rejected: insufficient margin" },
    { type: "info" as const, msg: "New listing detected: TOKEN/USDT" },
    { type: "warning" as const, msg: "Drawdown threshold approaching: 12.5%" },
  ];

  for (let i = 0; i < count; i++) {
    const msg = messages[Math.floor(Math.random() * messages.length)];
    alerts.push({
      id: `alert-${now}-${i}-${Math.random()}`,
      timestamp: now - i * 120000,
      type: msg.type,
      message: msg.msg,
    });
  }

  return alerts;
};

export const getGlobalMetrics = (performances: StrategyPerformance[]): GlobalMetrics => {
  const totalPnL = performances.reduce((sum, p) => sum + p.metrics.pnl, 0);
  const totalCapital = strategies.reduce((sum, s) => sum + s.capital, 0);

  return {
    totalPnL,
    totalPnLPercent: (totalPnL / totalCapital) * 100,
    sharpe: performances.reduce((sum, p) => sum + p.metrics.sharpe, 0) / performances.length,
    drawdown: Math.max(...performances.map((p) => p.metrics.drawdown)),
    activePositions: Math.floor(Math.random() * 50),
    dailyTradeCount: performances.reduce((sum, p) => sum + p.metrics.tradeCount, 0),
  };
};

export const getVenueColor = (type: VenueType): string => {
  switch (type) {
    case "crypto":
      return "#00F5D4";
    case "equities":
      return "#FFC300";
    case "fx":
      return "#8C6FF0";
  }
};

export const getVenueGradient = (type: VenueType): string => {
  switch (type) {
    case "crypto":
      return "from-cyan-400 to-teal-400";
    case "equities":
      return "from-amber-400 to-orange-400";
    case "fx":
      return "from-violet-400 to-indigo-500";
  }
};
