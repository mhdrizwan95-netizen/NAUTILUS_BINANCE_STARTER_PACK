/**
 * Dashboard Tab - "THE COCKPIT" - High-Density Mission Control
 * 
 * Real-time dashboard showing portfolio metrics, active strategies, and live trades.
 * Consumes data from Zustand stores which are populated via WebSocket/API.
 */
import { useRealTimeData } from '../../lib/store';
import { usePortfolio, useRecentTrades, useAllStrategies, useSystemHealth, useTotalPnl } from '../../lib/tradingStore';
import { cn } from '../../lib/utils';
import { GlassCard } from '../ui/GlassCard';

// Unified strategy item type for display
interface StrategyDisplayItem {
  name: string;
  status: string;
  confidence?: number;
  signal?: number;
  pnl?: number;
  pnlHistory?: number[];
}

export function DashboardTab() {
  // Real-time Data from stores (populated by WebSocket)
  const { globalMetrics, performances, venues } = useRealTimeData();
  const portfolio = usePortfolio();
  const recentTrades = useRecentTrades(50);
  const strategies = useAllStrategies();
  const systemHealth = useSystemHealth();
  const totalPnl = useTotalPnl();

  // Derived Vitals
  const netEquity = portfolio.equity || 0;
  const dailyPnL = totalPnl || globalMetrics?.totalPnL || 0;
  const latency = venues.find(v => v.name === 'BINANCE')?.latency ||
    (venues.find(v => v.status === 'connected')?.latency) || 0;
  const isOnline = venues.some(v => v.status === 'connected');
  const tradingEnabled = systemHealth.tradingEnabled;

  // Strategies Data - unify different data sources
  const strategyItems: StrategyDisplayItem[] = strategies.length > 0
    ? strategies.map(s => ({
      name: s.name,
      status: s.enabled ? 'active' : 'inactive',
      confidence: s.confidence,
      signal: s.signal,
    }))
    : performances.map(p => ({
      name: p.strategyId,
      status: 'active',
      pnl: p.metrics?.pnl || 0,
      pnlHistory: p.metrics?.sparkline || [],
    }));

  // Format helpers
  const formatUsd = (val: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(val);

  const formatPnl = (val: number) => {
    const formatted = formatUsd(Math.abs(val));
    return val >= 0 ? `+${formatted}` : `-${formatted}`;
  };

  return (
    <div className="flex flex-col !gap-6 w-full">

      {/* HEADER: Key Metrics */}
      <div className="grid grid-cols-4 !gap-4">
        <GlassCard className="flex items-center !gap-4 !p-4" neonAccent="cyan">
          <div className="!h-10 !w-10 rounded-lg bg-cyan-500/20 flex items-center justify-center">
            <span className="text-cyan-400 !text-lg">💰</span>
          </div>
          <div>
            <div className="!text-xs text-zinc-400 uppercase tracking-wider">Net Equity</div>
            <div className="!text-lg font-mono font-bold text-zinc-100">{formatUsd(netEquity)}</div>
          </div>
        </GlassCard>

        <GlassCard className="flex items-center !gap-4 !p-4" neonAccent={dailyPnL >= 0 ? "green" : "red"}>
          <div className={cn(
            "!h-10 !w-10 rounded-lg flex items-center justify-center",
            dailyPnL >= 0 ? "bg-emerald-500/20" : "bg-red-500/20"
          )}>
            <span className={dailyPnL >= 0 ? "text-emerald-400" : "text-red-400"}>📈</span>
          </div>
          <div>
            <div className="!text-xs text-zinc-400 uppercase tracking-wider">Daily P&L</div>
            <div className={cn(
              "!text-lg font-mono font-bold",
              dailyPnL >= 0 ? "text-emerald-400" : "text-red-400"
            )}>
              {formatPnl(dailyPnL)}
            </div>
          </div>
        </GlassCard>

        <GlassCard className="flex items-center !gap-4 !p-4" neonAccent={isOnline ? "green" : "red"}>
          <div className={cn(
            "!h-10 !w-10 rounded-lg flex items-center justify-center",
            isOnline ? "bg-emerald-500/20" : "bg-red-500/20"
          )}>
            <span className={isOnline ? "text-emerald-400" : "text-red-400"}>📡</span>
          </div>
          <div>
            <div className="!text-xs text-zinc-400 uppercase tracking-wider">Status</div>
            <div className={cn(
              "!text-lg font-mono font-bold",
              isOnline ? "text-emerald-400" : "text-red-400"
            )}>
              {isOnline ? 'Connected' : 'Offline'}
            </div>
            {latency > 0 && <div className="!text-xs text-zinc-500">{latency}ms</div>}
          </div>
        </GlassCard>

        <GlassCard className="flex items-center !gap-4 !p-4" neonAccent={tradingEnabled ? "green" : "amber"}>
          <div className={cn(
            "!h-10 !w-10 rounded-lg flex items-center justify-center",
            tradingEnabled ? "bg-emerald-500/20" : "bg-amber-500/20"
          )}>
            <span className={tradingEnabled ? "text-emerald-400" : "text-amber-400"}>⚡</span>
          </div>
          <div>
            <div className="!text-xs text-zinc-400 uppercase tracking-wider">Trading</div>
            <div className={cn(
              "!text-lg font-mono font-bold",
              tradingEnabled ? "text-emerald-400" : "text-amber-400"
            )}>
              {tradingEnabled ? 'ENABLED' : 'DISABLED'}
            </div>
          </div>
        </GlassCard>
      </div>

      {/* MAIN ROW: Strategies & Trades */}
      <div className="grid grid-cols-2 !gap-6">

        {/* Active Strategies */}
        <GlassCard title="Active Strategies" neonAccent="cyan">
          {strategyItems.length === 0 ? (
            <div className="text-zinc-500 !text-sm !py-6 text-center">
              No active strategies. Waiting for data...
            </div>
          ) : (
            <div className="!space-y-2">
              {strategyItems.map((s, i) => (
                <div key={i} className="flex items-center justify-between !py-2 border-b border-white/5 last:border-0">
                  <div className="flex items-center !gap-3">
                    <div className={cn(
                      "!w-2 !h-2 rounded-full",
                      s.status === 'active' ? "bg-emerald-400" : "bg-zinc-600"
                    )} />
                    <span className="text-zinc-200 font-medium">{s.name}</span>
                  </div>
                  <div className="text-zinc-400 !text-sm font-mono">
                    {s.confidence !== undefined ? `${(s.confidence * 100).toFixed(0)}%` :
                      s.pnl !== undefined ? (
                        <span className={s.pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {formatPnl(s.pnl)}
                        </span>
                      ) : '—'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        {/* Recent Trades */}
        <GlassCard title="Recent Trades" neonAccent="blue">
          {recentTrades.length === 0 ? (
            <div className="text-zinc-500 !text-sm !py-6 text-center">
              No recent trades. Waiting for fills...
            </div>
          ) : (
            <div className="!space-y-2 !max-h-[250px] overflow-y-auto">
              {recentTrades.slice(0, 10).map((trade, i) => (
                <div key={i} className="flex items-center justify-between !py-2 border-b border-white/5 last:border-0">
                  <div className="flex items-center !gap-2">
                    <span className={cn(
                      "!text-xs !px-2 !py-0.5 rounded font-medium",
                      trade.side === 'BUY' ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
                    )}>
                      {trade.side}
                    </span>
                    <span className="text-zinc-200">{trade.symbol}</span>
                  </div>
                  <div className="text-zinc-400 !text-sm font-mono">
                    {trade.quantity.toFixed(4)} @ {trade.price.toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      {/* BOTTOM ROW: Open Positions */}
      {portfolio.positions.length > 0 && (
        <GlassCard title="Open Positions" neonAccent="green">
          <div className="!space-y-2">
            {portfolio.positions.map((pos, i) => (
              <div key={i} className="flex items-center justify-between !py-2 border-b border-white/5 last:border-0">
                <div className="text-zinc-200 font-medium">{pos.symbol}</div>
                <div className="flex items-center !gap-6">
                  <span className={cn(
                    "!text-sm font-mono",
                    pos.quantity > 0 ? "text-emerald-400" : "text-red-400"
                  )}>
                    {pos.quantity > 0 ? 'LONG' : 'SHORT'} {Math.abs(pos.quantity).toFixed(4)}
                  </span>
                  <span className={cn(
                    "font-mono font-medium",
                    pos.unrealizedPnl >= 0 ? "text-emerald-400" : "text-red-400"
                  )}>
                    {formatPnl(pos.unrealizedPnl)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}
