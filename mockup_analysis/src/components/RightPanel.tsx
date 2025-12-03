import { X, TrendingUp, Activity, Zap, AlertCircle } from 'lucide-react';
import { Button } from './ui/button';
import { ScrollArea } from './ui/scroll-area';
import { Badge } from './ui/badge';
import { LineChart, Line, AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import type { StrategyPerformance, Strategy, Venue, Trade } from '../types/trading';
import { getVenueColor, getVenueGradient } from '../lib/mockData';
import { motion, AnimatePresence } from 'motion/react';

interface RightPanelProps {
  performance: StrategyPerformance | null;
  strategy: Strategy | null;
  venue: Venue | null;
  trades: Trade[];
  onClose: () => void;
}

export function RightPanel({ performance, strategy, venue, trades, onClose }: RightPanelProps) {
  if (!performance || !strategy || !venue) return null;

  const venueColor = getVenueColor(venue.type);
  const venueGradient = getVenueGradient(venue.type);

  // Generate equity curve data
  const equityCurveData = performance.metrics.sparkline.map((value, index) => ({
    index,
    value,
  }));

  // Generate confidence timeline (mock data)
  const confidenceData = Array.from({ length: 24 }, (_, i) => ({
    time: i,
    confidence: 0.5 + Math.random() * 0.4,
  }));

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const strategyTrades = trades.filter(
    (t) => t.strategyId === strategy.id && t.venueId === venue.id
  );

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: 20 }}
        className="w-96 bg-zinc-900/70 backdrop-blur-xl border-l border-zinc-800/50 flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800/50">
          <div>
            <h2 className="text-zinc-100 mb-1">
              {strategy.name} • {venue.name}
            </h2>
            <p className="text-xs text-zinc-500">Detailed Performance View</p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="h-8 w-8 p-0 text-zinc-400 hover:text-zinc-100"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-6 space-y-6">
            {/* Key Metrics */}
            <div className="space-y-3">
              <h3 className="text-xs text-zinc-500 tracking-wider">KEY METRICS</h3>
              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  label="PnL"
                  value={formatCurrency(performance.metrics.pnl)}
                  subtitle={`${performance.metrics.pnlPercent >= 0 ? '+' : ''}${performance.metrics.pnlPercent.toFixed(2)}%`}
                  color={performance.metrics.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}
                />
                <MetricCard
                  label="Win Rate"
                  value={`${(performance.metrics.winRate * 100).toFixed(1)}%`}
                  color="text-cyan-400"
                />
                <MetricCard
                  label="Sharpe Ratio"
                  value={performance.metrics.sharpe.toFixed(2)}
                  color="text-violet-400"
                />
                <MetricCard
                  label="Max Drawdown"
                  value={`${(performance.metrics.drawdown * 100).toFixed(1)}%`}
                  color="text-amber-400"
                />
              </div>
            </div>

            {/* Equity Curve */}
            <div className="space-y-3">
              <h3 className="text-xs text-zinc-500 tracking-wider">EQUITY CURVE</h3>
              <div className="h-32 bg-zinc-800/30 rounded-xl p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityCurveData}>
                    <defs>
                      <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={venueColor} stopOpacity={0.3} />
                        <stop offset="100%" stopColor={venueColor} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke={venueColor}
                      fill="url(#equityGradient)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Confidence Timeline */}
            <div className="space-y-3">
              <h3 className="text-xs text-zinc-500 tracking-wider">CONFIDENCE TIMELINE</h3>
              <div className="h-24 bg-zinc-800/30 rounded-xl p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={confidenceData}>
                    <Line
                      type="monotone"
                      dataKey="confidence"
                      stroke={venueColor}
                      strokeWidth={2}
                      dot={false}
                    />
                    <YAxis domain={[0, 1]} hide />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-zinc-600">
                Current model confidence: {(confidenceData[confidenceData.length - 1].confidence * 100).toFixed(1)}%
              </p>
            </div>

            {/* Top Symbols */}
            <div className="space-y-3">
              <h3 className="text-xs text-zinc-500 tracking-wider">TOP SYMBOLS</h3>
              <div className="space-y-2">
                {performance.metrics.topSymbols.map((symbol, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-zinc-700 to-zinc-800 flex items-center justify-center">
                        <TrendingUp className="w-4 h-4 text-zinc-400" />
                      </div>
                      <span className="text-xs text-zinc-300 font-mono">{symbol.symbol}</span>
                    </div>
                    <span
                      className={`text-xs font-mono ${
                        symbol.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                      }`}
                    >
                      {formatCurrency(symbol.pnl)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Trades */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs text-zinc-500 tracking-wider">RECENT TRADES</h3>
                <Badge variant="outline" className="text-xs border-zinc-700/50 text-zinc-500">
                  {strategyTrades.length}
                </Badge>
              </div>
              <div className="space-y-2">
                {strategyTrades.slice(0, 8).map((trade) => (
                  <div
                    key={trade.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30"
                  >
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <Badge
                          variant="outline"
                          className={`text-xs px-2 py-0 ${
                            trade.side === 'buy'
                              ? 'border-emerald-400/30 text-emerald-400'
                              : 'border-red-400/30 text-red-400'
                          }`}
                        >
                          {trade.side.toUpperCase()}
                        </Badge>
                        <span className="text-xs text-zinc-400 font-mono">{trade.symbol}</span>
                      </div>
                      <span className="text-xs text-zinc-600 font-mono">
                        {formatTime(trade.timestamp)}
                      </span>
                    </div>
                    {trade.pnl !== undefined && (
                      <span
                        className={`text-xs font-mono ${
                          trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                        }`}
                      >
                        {formatCurrency(trade.pnl)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Health Status */}
            <div className="space-y-3">
              <h3 className="text-xs text-zinc-500 tracking-wider">HEALTH STATUS</h3>
              <div className="space-y-2">
                <HealthItem
                  label="Connection"
                  status={venue.status === 'connected' ? 'optimal' : 'warning'}
                  value={`${venue.latency}ms`}
                />
                <HealthItem
                  label="Risk Exposure"
                  status={performance.metrics.var < 0.02 ? 'optimal' : 'warning'}
                  value={`${(performance.metrics.var * 100).toFixed(1)}%`}
                />
                <HealthItem
                  label="Trade Frequency"
                  status="optimal"
                  value={`${performance.metrics.tradeCount} / day`}
                />
              </div>
            </div>
          </div>
        </ScrollArea>
      </motion.div>
    </AnimatePresence>
  );
}

function MetricCard({
  label,
  value,
  subtitle,
  color,
}: {
  label: string;
  value: string;
  subtitle?: string;
  color: string;
}) {
  return (
    <div className="bg-zinc-800/30 rounded-xl p-3">
      <div className="text-xs text-zinc-600 mb-1">{label}</div>
      <div className={`font-mono ${color} mb-0.5`}>{value}</div>
      {subtitle && <div className="text-xs text-zinc-600 font-mono">{subtitle}</div>}
    </div>
  );
}

function HealthItem({
  label,
  status,
  value,
}: {
  label: string;
  status: 'optimal' | 'warning' | 'critical';
  value: string;
}) {
  const statusColor = {
    optimal: 'bg-emerald-400',
    warning: 'bg-amber-400',
    critical: 'bg-red-400',
  }[status];

  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30">
      <div className="flex items-center gap-2">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} />
        <span className="text-xs text-zinc-400">{label}</span>
      </div>
      <span className="text-xs text-zinc-300 font-mono">{value}</span>
    </div>
  );
}
