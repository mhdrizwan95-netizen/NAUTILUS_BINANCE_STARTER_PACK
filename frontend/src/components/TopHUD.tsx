import { Activity, Pause, Play, Power, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { motion } from "motion/react";
import { useId, useMemo } from "react";

import { useRenderCounter } from "@/lib/debug/why";
import { isDryRunMode } from "@/lib/security";

import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Switch } from "./ui/switch";

export interface TopHudMetrics {
  totalPnl: number;
  winRate: number;
  sharpe: number;
  maxDrawdown: number;
  openPositions: number;
}

export interface TopHudVenue {
  name: string;
  status: "ok" | "warn" | "down";
  latencyMs: number;
  queue: number;
}

export interface TopHUDProps {
  mode: "paper" | "live";
  metrics?: TopHudMetrics | null;
  venues?: TopHudVenue[] | null;
  isConnected?: boolean;
  isLoading?: boolean;
  onModeChange: (mode: "paper" | "live") => void | Promise<void>;
  onKillSwitch: () => void | Promise<void>;
  onPause: () => void | Promise<void>;
  onResume: () => void | Promise<void>;
  onFlatten: () => void | Promise<void>;
  controlState?: "pause" | "resume" | "flatten" | "kill" | null;
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
  useRenderCounter("TopHUD");
  const dryRunMode = isDryRunMode();
  const switchId = useId();
  const switchLabelId = `${switchId}-label`;
  const killDescriptionId = useId();

  const metricsAvailable = Boolean(metrics) && !isLoading;

  const totalPnlValue = metricsAvailable && metrics ? formatCurrency(metrics.totalPnl) : "--";
  const winRateValue =
    metricsAvailable && metrics ? `${formatPercent(metrics.winRate)} win` : undefined;
  const sharpeValue = metricsAvailable && metrics ? metrics.sharpe.toFixed(2) : "--";
  const drawdownValue =
    metricsAvailable && metrics ? `${(metrics.maxDrawdown * 100).toFixed(2)}%` : "--";
  const positionsValue = metricsAvailable && metrics ? metrics.openPositions.toString() : "--";

  const venueSnapshot = useMemo(() => venues ?? [], [venues]);

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="px-6 py-3 bg-zinc-900/70 backdrop-blur-xl border-b border-zinc-800/40 shadow-[0_10px_30px_rgba(0,0,0,0.35)]"
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="absolute inset-0 w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-indigo-500 opacity-30 blur-lg" />
            <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-indigo-500">
              <Activity className="h-4 w-4 text-zinc-950" aria-hidden="true" />
            </div>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight text-zinc-100">NAUTILUS</h1>
              {dryRunMode && (
                <Badge className="bg-amber-500/20 text-amber-200 border border-amber-400/30">
                  DRY RUN
                </Badge>
              )}
              {isConnected ? (
                <Wifi className="h-4 w-4 text-emerald-400" aria-hidden="true" />
              ) : (
                <WifiOff className="h-4 w-4 text-red-400" aria-hidden="true" />
              )}
            </div>
            <p className="text-xs tracking-[0.3em] text-zinc-500">TERMINAL</p>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-zinc-800/70 bg-zinc-900/60 px-4 py-2">
          <span className={`text-xs ${mode === "paper" ? "text-amber-400" : "text-zinc-500"}`}>
            PAPER
          </span>
          <span id={switchLabelId} className="sr-only">
            Trading mode
          </span>
          <Switch
            id={switchId}
            aria-labelledby={switchLabelId}
            checked={mode === "live"}
            onCheckedChange={(checked: boolean) => {
              const nextMode = checked ? "live" : "paper";
              void onModeChange(nextMode);
            }}
          />
          <span className={`text-xs ${mode === "live" ? "text-emerald-400" : "text-zinc-500"}`}>
            LIVE
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void onPause()}
            disabled={controlState === "pause" || !tradingEnabled}
            className="gap-2 border-amber-400/30 text-amber-300 hover:bg-amber-500/10"
          >
            <Pause className="h-4 w-4" aria-hidden="true" />
            Pause
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void onResume()}
            disabled={controlState === "resume" || tradingEnabled}
            className="gap-2 border-emerald-400/30 text-emerald-300 hover:bg-emerald-500/10"
          >
            <Play className="h-4 w-4" aria-hidden="true" />
            Resume
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void onFlatten()}
            disabled={controlState === "flatten"}
            className="gap-2 border-cyan-400/30 text-cyan-300 hover:bg-cyan-500/10"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Flatten
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => void onKillSwitch()}
            disabled={controlState === "kill"}
            className="gap-2 border border-red-500/40 bg-red-500/10 text-red-400 hover:bg-red-500/20"
            aria-describedby={killDescriptionId}
          >
            <Power className="h-4 w-4" aria-hidden="true" />
            KILL
          </Button>
          <span id={killDescriptionId} className="sr-only">
            Immediately disable live trading across all venues.
          </span>
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-6">
          <MetricDisplay label="Total PnL" value={totalPnlValue} subtitle={winRateValue} />
          <MetricDivider />
          <MetricDisplay
            label="Sharpe"
            value={sharpeValue}
            subtitle="Risk-adjusted"
            accent="text-cyan-400"
          />
          <MetricDivider />
          <MetricDisplay
            label="Max Drawdown"
            value={drawdownValue}
            subtitle="Peak to trough"
            accent="text-amber-400"
          />
          <MetricDivider />
          <MetricDisplay label="Open Positions" value={positionsValue} accent="text-zinc-300" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {venueSnapshot.length ? (
            venueSnapshot.map((venue) => <VenueChip key={venue.name} venue={venue} />)
          ) : (
            <span className="text-xs text-zinc-500">No venue telemetry</span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function MetricDivider() {
  return <div className="hidden h-8 w-px bg-zinc-800/70 md:block" />;
}

function MetricDisplay({
  label,
  value,
  subtitle,
  accent = "text-emerald-400",
}: {
  label: string;
  value: string;
  subtitle?: string;
  accent?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-zinc-500 tracking-wider">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className={`font-mono text-base ${accent}`}>{value}</span>
        {subtitle && <span className="text-xs font-mono text-zinc-600">{subtitle}</span>}
      </div>
    </div>
  );
}

function VenueChip({ venue }: { venue: TopHudVenue }) {
  const status =
    venue.status === "ok" ? "connected" : venue.status === "warn" ? "degraded" : "offline";
  const statusColor =
    status === "connected"
      ? "bg-emerald-400"
      : status === "degraded"
        ? "bg-amber-400"
        : "bg-zinc-600";

  return (
    <div className="flex items-center gap-2 rounded-lg border border-zinc-800/60 bg-zinc-900/40 px-3 py-1.5">
      <div className="relative">
        <div className={`h-2 w-2 rounded-full ${statusColor}`} />
        {status === "connected" && (
          <motion.div
            className={`absolute inset-0 h-2 w-2 rounded-full ${statusColor}`}
            animate={{ scale: [1, 2, 1], opacity: [1, 0, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        )}
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-xs font-mono text-zinc-200">{venue.name}</span>
        <span className="text-[10px] font-mono text-zinc-500">
          {venue.latencyMs ?? 0}ms · q{venue.queue ?? 0}
        </span>
      </div>
    </div>
  );
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}
