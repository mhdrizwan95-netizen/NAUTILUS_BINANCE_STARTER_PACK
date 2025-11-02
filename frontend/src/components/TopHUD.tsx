import { useId } from 'react';
import type { ReactNode } from 'react';
import { Power, Activity, Wifi, WifiOff } from 'lucide-react';
import { Switch } from './ui/switch';
import { Button } from './ui/button';
import { toast } from 'sonner';
import { motion } from 'motion/react';

export interface TopHudMetrics {
  totalPnl: number;
  winRate: number;
  sharpe: number;
  maxDrawdown: number;
  openPositions: number;
}

export interface TopHudVenue {
  name: string;
  status: 'ok' | 'warn' | 'down';
  latencyMs: number;
  queue: number;
}

export interface TopHUDProps {
  mode: 'paper' | 'live';
  metrics?: TopHudMetrics | null;
  venues?: TopHudVenue[] | null;
  isConnected?: boolean;
  isLoading?: boolean;
  onModeChange: (mode: 'paper' | 'live') => void;
  onKillSwitch: () => void;
}

export function TopHUD({
  mode,
  metrics,
  venues,
  isConnected = false,
  isLoading = false,
  onModeChange,
  onKillSwitch,
}: TopHUDProps) {
  const switchId = useId();
  const switchLabelId = `${switchId}-label`;

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);

  const formatPercent = (value: number) => `${(value * 100).toFixed(0)}%`;
  const formatDrawdown = (value: number) => `${(value * 100).toFixed(2)}%`;

  const metricsAvailable = Boolean(metrics) && !isLoading;

  const totalPnlValue = metricsAvailable && metrics ? formatCurrency(metrics.totalPnl) : '--';
  const winRateValue = metricsAvailable && metrics ? `${formatPercent(metrics.winRate)} win` : undefined;
  const sharpeValue = metricsAvailable && metrics ? metrics.sharpe.toFixed(2) : '--';
  const drawdownValue = metricsAvailable && metrics ? formatDrawdown(metrics.maxDrawdown) : '--';
  const positionsValue = metricsAvailable && metrics ? metrics.openPositions.toString() : '--';

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
          <span id={switchLabelId} className="sr-only">
            Trading mode
          </span>
          <Switch
            id={switchId}
            aria-labelledby={switchLabelId}
            checked={mode === 'live'}
            onCheckedChange={(checked: boolean) => {
              const nextMode = checked ? 'live' : 'paper';
              onModeChange(nextMode);
              toast.success(`Switched to ${nextMode.toUpperCase()} mode`, {
                description: nextMode === 'live' ? 'Real capital at risk' : 'Simulated trading active',
              });
            }}
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
              onKillSwitch();
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
            value={totalPnlValue}
            subtitle={winRateValue}
            color={
              metricsAvailable && metrics
                ? metrics.totalPnl >= 0
                  ? 'text-emerald-400'
                  : 'text-red-400'
                : 'text-zinc-600'
            }
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Sharpe"
            value={sharpeValue}
            color={
              metricsAvailable && metrics
                ? metrics.sharpe > 1
                  ? 'text-cyan-400'
                  : 'text-zinc-400'
                : 'text-zinc-600'
            }
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Drawdown"
            value={drawdownValue}
            color={
              metricsAvailable && metrics
                ? metrics.maxDrawdown < 0.1
                  ? 'text-zinc-400'
                  : 'text-amber-400'
                : 'text-zinc-600'
            }
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Positions"
            value={positionsValue}
            color={metricsAvailable ? 'text-zinc-300' : 'text-zinc-600'}
          />
        </div>

        {/* Right: Venue Status */}
        <div className="flex items-center gap-2">
          {(venues ?? []).map((venue) => (
            <VenueIndicator key={venue.name} venue={venue} />
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
  value: ReactNode;
  subtitle?: ReactNode;
  color?: string;
}) {
  const isText = typeof value === 'string' || typeof value === 'number';

  return (
    <div className="flex flex-col">
      <span className="text-xs text-zinc-500 tracking-wider">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className={isText ? `font-mono ${color ?? 'text-zinc-300'}` : 'font-mono text-zinc-300'}>
          {value}
        </span>
        {subtitle && <span className="text-xs text-zinc-600 font-mono">{subtitle}</span>}
      </div>
    </div>
  );
}

function VenueIndicator({ venue }: { venue: TopHudVenue }) {
  const statusColor = {
    ok: 'bg-emerald-400',
    warn: 'bg-amber-400',
    down: 'bg-red-500',
  }[venue.status];

  const statusLabel = {
    ok: 'Healthy',
    warn: 'Degraded',
    down: 'Offline',
  }[venue.status];

  return (
    <div className="px-3 py-1.5 rounded-lg bg-zinc-800/50 border border-zinc-700/40 flex items-center gap-3">
      <div className="relative">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} />
        {venue.status === 'ok' && (
          <motion.div
            className={`w-2 h-2 rounded-full ${statusColor} absolute inset-0`}
            animate={{ scale: [1, 2, 1], opacity: [1, 0, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        )}
      </div>
      <div className="flex flex-col">
        <span className="text-xs text-zinc-200 tracking-wide">{venue.name}</span>
        <span className="text-[10px] text-zinc-500 font-mono">
          {statusLabel} · {venue.latencyMs}ms · q{venue.queue}
        </span>
      </div>
    </div>
  );
}
