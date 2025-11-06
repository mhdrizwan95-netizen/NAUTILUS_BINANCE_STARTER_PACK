import { useId } from 'react';
import type { ReactNode } from 'react';
import { Power, Activity, Wifi, WifiOff, Pause, Play, RefreshCw } from 'lucide-react';
import { Switch } from './ui/switch';
import { Button } from './ui/button';
import { motion } from 'motion/react';
import { Badge } from './ui/badge';
import { useRenderCounter } from '@/lib/debug/why';
import { isDryRunMode } from '@/lib/security';

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
  onModeChange: (mode: 'paper' | 'live') => void | Promise<void>;
  onKillSwitch: () => void | Promise<void>;
  onPause: () => void | Promise<void>;
  onResume: () => void | Promise<void>;
  onFlatten: () => void | Promise<void>;
  controlState?: 'pause' | 'resume' | 'flatten' | 'kill' | null;
  tradingEnabled?: boolean;
}

export function TopHUD({
  mode,
  metrics,
  venues,
  isConnected = false,
  isLoading = false,
  onModeChange,
  onKillSwitch,
  onPause,
  onResume,
  onFlatten,
  controlState = null,
  tradingEnabled = true,
}: TopHUDProps) {
  useRenderCounter('TopHUD');
  const dryRunMode = isDryRunMode();
  const switchId = useId();
  const switchLabelId = `${switchId}-label`;
  const killDescriptionId = useId();
  const statusLiveId = useId();

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
              <Activity className="w-4 h-4 text-zinc-900" aria-hidden="true" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-zinc-100 tracking-tight">NAUTILUS</h1>
              {dryRunMode && (
                <Badge className="bg-amber-500/20 text-amber-200 border border-amber-400/30">
                  DRY RUN
                </Badge>
              )}
              {isConnected ? (
                <Wifi className="w-4 h-4 text-emerald-400" aria-hidden="true" />
              ) : (
                <WifiOff className="w-4 h-4 text-red-400" aria-hidden="true" />
              )}
              <span className="sr-only">
                {isConnected ? 'Connected to engine and market data' : 'Disconnected from engine and market data'}
              </span>
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
              void onModeChange(nextMode);
            }}
          />
          <span className={`text-xs ${mode === 'live' ? 'text-emerald-400' : 'text-zinc-500'}`}>
            LIVE
          </span>
        </div>

        {/* Right: Kill Switch */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void onPause();
            }}
            disabled={controlState === 'pause' || !tradingEnabled}
            className="gap-2 border-amber-400/30 text-amber-400 hover:bg-amber-500/10"
          >
            <Pause className="w-4 h-4" aria-hidden="true" />
            Pause
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void onResume();
            }}
            disabled={controlState === 'resume' || tradingEnabled}
            className="gap-2 border-emerald-400/30 text-emerald-400 hover:bg-emerald-500/10"
          >
            <Play className="w-4 h-4" aria-hidden="true" />
            Resume
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void onFlatten();
            }}
            disabled={controlState === 'flatten'}
            className="gap-2 border-cyan-400/30 text-cyan-300 hover:bg-cyan-500/10"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
            Flatten
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              void onKillSwitch();
            }}
            disabled={controlState === 'kill'}
            className="gap-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30"
            aria-describedby={killDescriptionId}
          >
            <Power className="w-4 h-4" aria-hidden="true" />
            KILL
          </Button>
          <span id={killDescriptionId} className="sr-only">
            Immediately disable live trading across all venues.
          </span>
          <Badge
            variant={tradingEnabled ? 'secondary' : 'destructive'}
            id={statusLiveId}
            role="status"
            aria-live="polite"
            aria-atomic="true"
            className="uppercase tracking-wide"
          >
            {tradingEnabled ? 'Trading enabled' : 'Trading paused'}
          </Badge>
        </div>
      </div>

      {/* Row 2: Global Metrics & Venue Status */}
      <div className="flex items-center justify-between">
        {/* Left: Global Metrics */}
        <dl className="grid gap-4 sm:flex sm:items-center sm:gap-8" aria-live="polite" aria-describedby={statusLiveId}>
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
          <MetricDisplay
            label="Positions"
            value={positionsValue}
            color={metricsAvailable ? 'text-zinc-300' : 'text-zinc-600'}
          />
        </dl>

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
    <>
      <dt className="text-xs text-zinc-500 tracking-wider">{label}</dt>
      <dd className="flex items-baseline gap-2">
        <span className={isText ? `font-mono ${color ?? 'text-zinc-300'}` : 'font-mono text-zinc-300'}>
          {value}
        </span>
        {subtitle && <span className="text-xs text-zinc-600 font-mono">{subtitle}</span>}
      </dd>
    </>
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
    <div
      className="px-3 py-1.5 rounded-lg bg-zinc-800/50 border border-zinc-700/40 flex items-center gap-3"
      role="status"
      aria-live="polite"
      aria-label={`${venue.name} status ${statusLabel}. Latency ${venue.latencyMs} milliseconds. Queue depth ${venue.queue}.`}
    >
      <div className="relative">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} aria-hidden="true" />
        {venue.status === 'ok' && (
          <motion.div
            className={`w-2 h-2 rounded-full ${statusColor} absolute inset-0`}
            animate={{ scale: [1, 2, 1], opacity: [1, 0, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
            aria-hidden="true"
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
