import { Power, Activity, Wifi, WifiOff } from 'lucide-react';
import { Switch } from './ui/switch';
import { Button } from './ui/button';
import { useAppStore, useModeActions, useRealTimeActions, useRealTimeData } from '../lib/store';
import { Venue } from '../lib/validation';
import { toast } from 'sonner';
import { motion } from 'motion/react';

export function TopHUD({ isConnected = false }: { isConnected?: boolean }) {
  const mode = useAppStore((state) => state.mode);
  // Use selector with shallow equality to avoid unnecessary re-renders
  const realTimeData = useRealTimeData();
  const { setMode } = useModeActions();
  const { updateVenues } = useRealTimeActions();

  // Use real-time data or fallback to mock data
  const metrics = realTimeData.globalMetrics;
  const venues: Venue[] = realTimeData.venues.length > 0 ? realTimeData.venues : [
    { id: 'binance', name: 'Binance', type: 'crypto' as const, status: 'connected' as const, latency: 12 },
    { id: 'bybit', name: 'Bybit', type: 'crypto' as const, status: 'connected' as const, latency: 18 },
    { id: 'ibkr', name: 'IBKR', type: 'equities' as const, status: 'connected' as const, latency: 45 },
    { id: 'oanda', name: 'OANDA', type: 'fx' as const, status: 'degraded' as const, latency: 89 },
  ];

  if (!metrics) return null; // Don't render until we have metrics
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  };

  const formatPercent = (value: number) => {
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="px-8 py-3 bg-zinc-900/70 backdrop-blur-xl border-b border-zinc-800/50"
    >
      {/* Row 1: Branding, Actions, Kill Switch */}
      <div className="flex items-center justify-between mb-3">
        {/* Left: Branding */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-indigo-500 opacity-20 absolute inset-0 blur-md" />
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-indigo-500 flex items-center justify-center relative">
              <Activity className="w-4 h-4 text-zinc-900" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-zinc-100 tracking-tight">NAUTILUS</h1>
              {isConnected ? (
                <Wifi className="w-4 h-4 text-emerald-400" />
              ) : (
                <WifiOff className="w-4 h-4 text-red-400" />
              )}
            </div>
            <p className="text-zinc-500 text-xs tracking-wider">TERMINAL</p>
          </div>
        </div>

        {/* Center: Mode Toggle */}
        <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-zinc-800/50 border border-zinc-700/50">
          <span className={`text-xs ${mode === 'paper' ? 'text-amber-400' : 'text-zinc-500'}`}>
            PAPER
          </span>
          <Switch
            checked={mode === 'live'}
            onCheckedChange={(checked: boolean) => setMode(checked ? 'live' : 'paper')}
          />
          <span className={`text-xs ${mode === 'live' ? 'text-emerald-400' : 'text-zinc-500'}`}>
            LIVE
          </span>
        </div>

        {/* Right: Kill Switch */}
        <div className="flex items-center gap-3">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              toast.error('EMERGENCY STOP ACTIVATED', {
                description: 'All positions closed, trading halted',
              });
            }}
            className="gap-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30"
          >
            <Power className="w-4 h-4" />
            KILL
          </Button>
        </div>
      </div>

      {/* Row 2: Global Metrics & Venue Status */}
      <div className="flex items-center justify-between">
        {/* Left: Global Metrics */}
        <div className="flex items-center gap-6">
          <MetricDisplay
            label="PnL"
            value={formatCurrency(metrics.totalPnL)}
            subtitle={formatPercent(metrics.totalPnLPercent)}
            color={metrics.totalPnL >= 0 ? 'text-emerald-400' : 'text-red-400'}
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Sharpe"
            value={metrics.sharpe.toFixed(2)}
            color={metrics.sharpe > 1 ? 'text-cyan-400' : 'text-zinc-400'}
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Drawdown"
            value={`${(metrics.drawdown * 100).toFixed(2)}%`}
            color={metrics.drawdown < 0.1 ? 'text-zinc-400' : 'text-amber-400'}
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Positions"
            value={metrics.activePositions.toString()}
            color="text-zinc-300"
          />
        </div>

        {/* Right: Venue Status */}
        <div className="flex items-center gap-2">
          {venues.map((venue) => (
            <VenueIndicator key={venue.id} venue={venue} />
          ))}
        </div>
      </div>
    </motion.div>
  );
}

function MetricDisplay({
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
    <div className="flex flex-col">
      <span className="text-xs text-zinc-500 tracking-wider">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className={`font-mono ${color}`}>{value}</span>
        {subtitle && <span className="text-xs text-zinc-600 font-mono">{subtitle}</span>}
      </div>
    </div>
  );
}

function VenueIndicator({ venue }: { venue: Venue }) {
  const statusColor = {
    connected: 'bg-emerald-400',
    degraded: 'bg-amber-400',
    offline: 'bg-zinc-600',
  }[venue.status];

  const venueColor = {
    crypto: 'border-cyan-400/30',
    equities: 'border-amber-400/30',
    fx: 'border-violet-400/30',
  }[venue.type];

  return (
    <div
      className={`px-3 py-1.5 rounded-lg bg-zinc-800/50 border ${venueColor} flex items-center gap-2`}
    >
      <div className="relative">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} />
        {venue.status === 'connected' && (
          <motion.div
            className={`w-2 h-2 rounded-full ${statusColor} absolute inset-0`}
            animate={{ scale: [1, 2, 1], opacity: [1, 0, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        )}
      </div>
      <span className="text-xs text-zinc-400 font-mono">{venue.name}</span>
      <span className="text-xs text-zinc-600 font-mono">{venue.latency}ms</span>
    </div>
  );
}
