/**
 * Dashboard Tab - "THE COCKPIT" - High-Density Mission Control
 * 
 * CSS Grid layout with Health Matrix, Active Strategies, and Live Order Feed
 */
import { useState, useEffect, useRef } from 'react';
import { Activity, Zap, Clock, TrendingUp, TrendingDown } from 'lucide-react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { usePortfolio, useSystemHealth, useRecentTrades } from '../../lib/tradingStore';
import { cn } from '../../lib/utils';

interface OrderFill {
  id: string;
  timestamp: number;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  fee: number;
}

interface StrategyCard {
  name: string;
  pnl: number;
  pnlHistory: number[];
  status: 'active' | 'paused';
}

export function DashboardTab() {
  const portfolio = usePortfolio();
  const health = useSystemHealth();
  const trades = useRecentTrades(100);

  // Simulated health metrics
  const [heartbeat, setHeartbeat] = useState(0.5); // seconds
  const [latency, setLatency] = useState(45); // ms
  const [apiWeight, setApiWeight] = useState(35); // % of limit

  // Simulated active strategies
  const [strategies] = useState<StrategyCard[]>([
    {
      name: 'HMM Policy',
      pnl: 1247.50,
      pnlHistory: Array.from({ length: 20 }, () => Math.random() * 100 + 1000),
      status: 'active'
    },
    {
      name: 'Momentum Breakout',
      pnl: 856.20,
      pnlHistory: Array.from({ length: 20 }, () => Math.random() * 80 + 800),
      status: 'active'
    },
    {
      name: 'Mean Reversion',
      pnl: -124.80,
      pnlHistory: Array.from({ length: 20 }, () => Math.random() * 50 - 150),
      status: 'paused'
    },
  ]);

  // Live order feed (virtualized)
  const orderFeedRef = useRef<HTMLDivElement>(null);
  const [orders, setOrders] = useState<OrderFill[]>(
    trades.map(t => ({
      id: t.id,
      timestamp: t.timestamp,
      symbol: t.symbol,
      side: t.side,
      quantity: t.quantity,
      price: t.price,
      fee: t.fee,
    }))
  );

  const rowVirtualizer = useVirtualizer({
    count: orders.length,
    getScrollElement: () => orderFeedRef.current,
    estimateSize: () => 40,
    overscan: 5,
  });

  // Simulate real-time updates
  useEffect(() => {
    const interval = setInterval(() => {
      setHeartbeat(0.3 + Math.random() * 0.5);
      setLatency(30 + Math.random() * 40);
      setApiWeight(20 + Math.random() * 40);
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-6 space-y-6">
      {/* Top Row: Health Matrix - Circular Gauges */}
      <div className="grid grid-cols-3 gap-6">
        <CircularGauge
          label="Heartbeat"
          value={heartbeat}
          max={2}
          unit="s"
          icon={<Activity className="h-5 w-5" />}
          thresholds={{ good: 1, warn: 1.5 }}
        />
        <CircularGauge
          label="Latency"
          value={latency}
          max={100}
          unit="ms"
          icon={<Clock className="h-5 w-5" />}
          thresholds={{ good: 50, warn: 80 }}
        />
        <CircularGauge
          label="API Weight"
          value={apiWeight}
          max={100}
          unit="%"
          icon={<Zap className="h-5 w-5" />}
          thresholds={{ good: 50, warn: 80 }}
        />
      </div>

      {/* Middle Row: Active Strategies with Sparklines */}
      <div className="glass p-6">
        <h3 className="text-lg font-semibold cyber-text mb-4">Active Strategies</h3>
        <div className="grid grid-cols-3 gap-4">
          {strategies.map((strategy) => (
            <StrategySparklineCard key={strategy.name} strategy={strategy} />
          ))}
        </div>
      </div>

      {/* Bottom Row: Live Order Feed (Virtualized) */}
      <div className="glass p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold cyber-text">Live Order Feed</h3>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full cyber-positive cyber-pulse" />
            <span className="text-xs cyber-text-dim">Real-time</span>
          </div>
        </div>

        {/* Header */}
        <div className="grid grid-cols-6 gap-4 px-4 py-2 text-xs font-semibold cyber-text-dim border-b border-white/10">
          <div>Time</div>
          <div>Symbol</div>
          <div className="text-right">Side</div>
          <div className="text-right">Qty</div>
          <div className="text-right">Price</div>
          <div className="text-right">Fee</div>
        </div>

        {/* Virtualized List */}
        <div ref={orderFeedRef} className="h-64 overflow-auto">
          <div
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const order = orders[virtualRow.index];
              return (
                <div
                  key={virtualRow.key}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: `${virtualRow.size}px`,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  className="grid grid-cols-6 gap-4 px-4 py-2 text-sm border-b border-white/5 hover:bg-white/5 transition-colors"
                >
                  <div className="cyber-text-dim font-mono text-xs">
                    {new Date(order.timestamp).toLocaleTimeString()}
                  </div>
                  <div className="cyber-text font-semibold">{order.symbol}</div>
                  <div className={cn(
                    'text-right font-mono font-bold',
                    order.side === 'BUY' ? 'cyber-positive' : 'cyber-negative'
                  )}>
                    {order.side}
                  </div>
                  <div className="text-right font-mono cyber-text">{order.quantity.toFixed(4)}</div>
                  <div className="text-right font-mono cyber-text">${order.price.toFixed(2)}</div>
                  <div className="text-right font-mono cyber-text-dim">${order.fee.toFixed(2)}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function CircularGauge({
  label,
  value,
  max,
  unit,
  icon,
  thresholds,
}: {
  label: string;
  value: number;
  max: number;
  unit: string;
  icon: React.ReactNode;
  thresholds: { good: number; warn: number };
}) {
  const percentage = (value / max) * 100;
  const circumference = 2 * Math.PI * 45; // radius = 45
  const offset = circumference - (percentage / 100) * circumference;

  const color =
    value <= thresholds.good
      ? 'cyber-positive'
      : value <= thresholds.warn
        ? 'neon-yellow'
        : 'cyber-negative';

  return (
    <div className="glass p-6">
      <div className="flex items-center gap-2 mb-4">
        <div className={color}>{icon}</div>
        <h4 className="text-sm font-semibold cyber-text">{label}</h4>
      </div>

      <div className="flex items-center justify-center">
        <div className="relative w-32 h-32">
          <svg className="transform -rotate-90" width="128" height="128">
            <circle
              cx="64"
              cy="64"
              r="45"
              stroke="rgba(255, 255, 255, 0.1)"
              strokeWidth="8"
              fill="none"
            />
            <circle
              cx="64"
              cy="64"
              r="45"
              stroke="currentColor"
              strokeWidth="8"
              fill="none"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              className={cn('transition-all duration-500', color)}
              strokeLinecap="round"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className={cn('text-2xl font-bold font-mono', color)}>
              {value.toFixed(value < 10 ? 1 : 0)}
            </div>
            <div className="text-xs cyber-text-dim">{unit}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StrategySparklineCard({ strategy }: { strategy: StrategyCard }) {
  const chartData = strategy.pnlHistory.map((pnl, i) => ({ index: i, pnl }));

  return (
    <div className="glass-panel p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold cyber-text">{strategy.name}</h4>
        <div className={cn(
          'w-2 h-2 rounded-full',
          strategy.status === 'active' ? 'cyber-positive cyber-pulse' : 'bg-gray-500'
        )} />
      </div>

      <div className={cn(
        'text-2xl font-bold font-mono mb-2',
        strategy.pnl > 0 ? 'cyber-positive' : 'cyber-negative'
      )}>
        {strategy.pnl > 0 ? '+' : ''}${strategy.pnl.toFixed(2)}
      </div>

      <ResponsiveContainer width="100%" height={40}>
        <LineChart data={chartData}>
          <Line
            type="monotone"
            dataKey="pnl"
            stroke={strategy.pnl > 0 ? '#00ff9d' : '#ff6b6b'}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
