/**
 * Dashboard Tab - "THE COCKPIT" - High-Density Mission Control
 * 
 * CSS Grid layout with Health Matrix, Active Strategies, and Live Order Feed
 */
import { useVirtualizer } from '@tanstack/react-virtual';
import { Activity, Zap, Wifi, TrendingUp, TrendingDown, DollarSign } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { LineChart, Line, ResponsiveContainer, YAxis, AreaChart, Area } from 'recharts';

import { cn } from '../../lib/utils';
import { GlassCard } from '../ui/GlassCard';

// Mock Data Interfaces
interface Order {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  status: 'FILLED' | 'NEW' | 'CANCELED';
  timestamp: number;
  fee: number;
}

interface StrategyCard {
  name: string;
  status: 'active' | 'paused' | 'error';
  pnl: number;
  pnlHistory: number[];
  allocation: number;
}

export function DashboardTab() {
  // State
  const [orders, setOrders] = useState<Order[]>([]);
  const [strategies, setStrategies] = useState<StrategyCard[]>([]);
  const [equityHistory, setEquityHistory] = useState<{ time: number; value: number }[]>([]);

  // Vitals
  const [netEquity] = useState(10450.20);
  const [dailyPnL] = useState(2.4);
  const [marginUsage] = useState(45);
  const [latency] = useState(32);

  // Initialize Mock Data
  useEffect(() => {
    // Strategies
    setStrategies([
      { name: 'HMM_Trend_v2', status: 'active', pnl: 1250.50, pnlHistory: Array(20).fill(0).map(() => Math.random() * 100), allocation: 0.4 },
      { name: 'MeanRev_Scalp', status: 'active', pnl: -45.20, pnlHistory: Array(20).fill(0).map(() => Math.random() * -50), allocation: 0.3 },
      { name: 'Meme_Sniper', status: 'paused', pnl: 0, pnlHistory: Array(20).fill(0), allocation: 0.1 },
    ]);

    // Equity History
    const history = [];
    let val = 10000;
    for (let i = 0; i < 50; i++) {
      val += (Math.random() - 0.4) * 100;
      history.push({ time: i, value: val });
    }
    setEquityHistory(history);

    // Orders
    const newOrders: Order[] = Array.from({ length: 50 }).map((_, i) => ({
      id: `ord_${i}`,
      symbol: Math.random() > 0.5 ? 'BTCUSDT' : 'ETHUSDT',
      side: Math.random() > 0.5 ? 'BUY' : 'SELL',
      quantity: Math.random() * 2,
      price: 40000 + Math.random() * 1000,
      status: 'FILLED',
      timestamp: Date.now() - i * 60000,
      fee: Math.random() * 5,
    }));
    setOrders(newOrders);
  }, []);

  // Virtualization for Order Feed
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: orders.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 40,
    overscan: 5,
  });

  return (
    <div className="p-8 space-y-8 min-h-screen flex flex-col max-w-[1920px] mx-auto w-full bg-deep-space text-zinc-100 font-header pb-20">

      {/* TOP HUD */}
      <div className="grid grid-cols-5 gap-6">
        <GlassCard className="flex items-center justify-between p-6 bg-white/5">
          <div>
            <div className="text-xs text-zinc-400 uppercase tracking-wider">Net Equity</div>
            <div className="text-xl font-data font-bold text-white">${netEquity.toLocaleString()}</div>
          </div>
          <DollarSign className="w-5 h-5 text-neon-green" />
        </GlassCard>

        <GlassCard className="flex items-center justify-between p-6 bg-white/5">
          <div>
            <div className="text-xs text-zinc-400 uppercase tracking-wider">24h PnL</div>
            <div className={cn("text-xl font-data font-bold", dailyPnL >= 0 ? "text-neon-green" : "text-neon-red")}>
              {dailyPnL >= 0 ? "+" : ""}{dailyPnL}%
            </div>
          </div>
          {dailyPnL >= 0 ? <TrendingUp className="w-5 h-5 text-neon-green" /> : <TrendingDown className="w-5 h-5 text-neon-red" />}
        </GlassCard>

        <GlassCard className="flex items-center justify-between p-6 bg-white/5">
          <div>
            <div className="text-xs text-zinc-400 uppercase tracking-wider">Margin Usage</div>
            <div className={cn("text-xl font-data font-bold", marginUsage > 80 ? "text-neon-red" : "text-neon-cyan")}>
              {marginUsage}%
            </div>
          </div>
          <Activity className="w-5 h-5 text-neon-cyan" />
        </GlassCard>

        <GlassCard className="flex items-center justify-between p-6 bg-white/5">
          <div>
            <div className="text-xs text-zinc-400 uppercase tracking-wider">API Latency</div>
            <div className="text-xl font-data font-bold text-neon-amber">{latency}ms</div>
          </div>
          <Zap className="w-5 h-5 text-neon-amber" />
        </GlassCard>

        <GlassCard className="flex items-center justify-between p-6 bg-white/5">
          <div>
            <div className="text-xs text-zinc-400 uppercase tracking-wider">System Status</div>
            <div className="text-xl font-data font-bold text-neon-green">ONLINE</div>
          </div>
          <Wifi className="w-5 h-5 text-neon-green" />
        </GlassCard>
      </div>

      {/* MAIN ROW: Equity Curve & Liquidation */}
      <div className="grid grid-cols-12 gap-8 h-[450px]">

        {/* Total Equity & PnL Curve */}
        <GlassCard title="Real-Time PnL Curve" neonAccent="blue" className="col-span-9 flex flex-col">
          <div className="flex-1 w-full h-full min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityHistory}>
                <defs>
                  <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#4361ee" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#4361ee" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis domain={['auto', 'auto']} hide />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#4361ee"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorEquity)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* Liquidation Thermometer */}
        <GlassCard title="Liquidation Risk" neonAccent={marginUsage > 80 ? "red" : "green"} className="col-span-3 flex flex-col items-center justify-center relative">
          <div className="w-16 h-72 bg-zinc-800/50 rounded-full relative overflow-hidden border border-white/5">
            <div
              className={cn(
                "absolute bottom-0 left-0 right-0 transition-all duration-500 ease-out",
                marginUsage > 80 ? "bg-neon-red box-glow-red" : "bg-neon-green box-glow-green"
              )}
              style={{ height: `${marginUsage}%` }}
            />
            {/* Ticks */}
            <div className="absolute inset-0 flex flex-col justify-between py-4 pointer-events-none">
              {[...Array(10)].map((_, i) => (
                <div key={i} className="w-full h-px bg-black/20" />
              ))}
            </div>
          </div>
          <div className="mt-6 text-center">
            <div className="text-3xl font-data font-bold text-white">{marginUsage}%</div>
            <div className="text-xs text-zinc-500 uppercase tracking-wider mt-1">Margin Used</div>
          </div>
        </GlassCard>
      </div>

      {/* BOTTOM ROW: Strategies & Feed */}
      <div className="grid grid-cols-12 gap-8">

        {/* Active Strategies */}
        <div className="col-span-4 flex flex-col gap-6">
          {strategies.map(strategy => (
            <GlassCard key={strategy.name} className="p-6" neonAccent={strategy.pnl >= 0 ? "green" : "red"}>
              <div className="flex justify-between items-start mb-4">
                <div>
                  <div className="font-bold text-white text-lg">{strategy.name}</div>
                  <div className={cn("text-xs uppercase tracking-wider mt-1", strategy.status === 'active' ? "text-neon-green" : "text-zinc-500")}>
                    {strategy.status}
                  </div>
                </div>
                <div className={cn("font-data font-bold text-xl", strategy.pnl >= 0 ? "text-neon-green" : "text-neon-red")}>
                  {strategy.pnl >= 0 ? "+" : ""}{strategy.pnl.toFixed(2)}
                </div>
              </div>
              <div className="h-16 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={strategy.pnlHistory.map((v, i) => ({ i, v }))}>
                    <Line type="monotone" dataKey="v" stroke={strategy.pnl >= 0 ? "#00ff9d" : "#ff6b6b"} strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          ))}
        </div>

        {/* Recent Fills (Feed) */}
        <GlassCard title="Live Order Feed" neonAccent="cyan" className="col-span-8 flex flex-col h-[600px]">
          <div className="grid grid-cols-6 gap-4 px-6 py-3 text-xs font-bold text-zinc-500 border-b border-white/5 uppercase tracking-wider shrink-0">
            <div>Time</div>
            <div>Symbol</div>
            <div className="text-right">Side</div>
            <div className="text-right">Qty</div>
            <div className="text-right">Price</div>
            <div className="text-right">Fee</div>
          </div>

          <div ref={parentRef} className="flex-1 overflow-auto min-h-0">
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
                    key={order.id}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    className="grid grid-cols-6 gap-4 px-6 items-center text-sm border-b border-white/5 hover:bg-white/5 transition-colors"
                  >
                    <div className="text-zinc-500 font-mono text-xs">
                      {new Date(order.timestamp).toLocaleTimeString()}
                    </div>
                    <div className="text-white font-semibold">{order.symbol}</div>
                    <div className={cn(
                      'text-right font-mono font-bold',
                      order.side === 'BUY' ? 'text-neon-green' : 'text-neon-red'
                    )}>
                      {order.side}
                    </div>
                    <div className="text-right font-mono text-zinc-300">{order.quantity.toFixed(4)}</div>
                    <div className="text-right font-mono text-zinc-300">${order.price.toFixed(2)}</div>
                    <div className="text-right font-mono text-zinc-500">${order.fee.toFixed(2)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
