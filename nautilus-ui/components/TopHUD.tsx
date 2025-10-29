"use client";

import { Activity, Power, Settings as SettingsIcon } from "lucide-react";
import { motion } from "framer-motion";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { GlobalMetrics, ModeType, Venue } from "@/lib/types";

interface TopHUDProps {
  mode: ModeType;
  onModeChange: (mode: ModeType) => void;
  metrics: GlobalMetrics;
  venues: Venue[];
  onKillSwitch: () => void;
  onSettingsClick: () => void;
}

export function TopHUD({
  mode,
  onModeChange,
  metrics,
  venues,
  onKillSwitch,
  onSettingsClick,
}: TopHUDProps) {
  const formatCurrency = (value: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);

  const formatPercent = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="px-8 py-3 bg-zinc-900/70 backdrop-blur-xl border-b border-zinc-800/50 sticky top-0 z-30"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-indigo-500 opacity-20 absolute inset-0 blur-md" />
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-indigo-500 flex items-center justify-center relative">
              <Activity className="w-4 h-4 text-zinc-900" />
            </div>
          </div>
          <div>
            <h1 className="text-zinc-100 tracking-tight">NAUTILUS</h1>
            <p className="text-zinc-500 text-xs tracking-wider">TERMINAL</p>
          </div>
        </div>

        <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-zinc-800/50 border border-zinc-700/50">
          <span className={`text-xs ${mode === "paper" ? "text-amber-400" : "text-zinc-500"}`}>PAPER</span>
          <Switch
            checked={mode === "live"}
            onCheckedChange={(checked) => onModeChange(checked ? "live" : "paper")}
          />
          <span className={`text-xs ${mode === "live" ? "text-emerald-400" : "text-zinc-500"}`}>LIVE</span>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={onSettingsClick}
            className="gap-2"
          >
            <SettingsIcon className="w-4 h-4" />
            <span className="text-xs">CONFIG</span>
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={onKillSwitch}
            className="gap-2"
          >
            <Power className="w-4 h-4" />
            KILL
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          <MetricDisplay
            label="PnL"
            value={formatCurrency(metrics.totalPnL)}
            subtitle={formatPercent(metrics.totalPnLPercent)}
            color={metrics.totalPnL >= 0 ? "text-emerald-400" : "text-red-400"}
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Sharpe"
            value={metrics.sharpe.toFixed(2)}
            color={metrics.sharpe > 1 ? "text-cyan-400" : "text-zinc-400"}
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay
            label="Drawdown"
            value={`${(metrics.drawdown * 100).toFixed(1)}%`}
            color={metrics.drawdown < 0.1 ? "text-zinc-400" : "text-amber-400"}
          />
          <div className="w-px h-8 bg-zinc-700/50" />
          <MetricDisplay label="Positions" value={metrics.activePositions.toString()} color="text-zinc-300" />
        </div>

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
    connected: "bg-emerald-400",
    degraded: "bg-amber-400",
    offline: "bg-zinc-600",
  }[venue.status];

  const venueColor = {
    crypto: "border-cyan-400/30",
    equities: "border-amber-400/30",
    fx: "border-violet-400/30",
  }[venue.type];

  return (
    <div className={`px-3 py-1.5 rounded-lg bg-zinc-800/50 border ${venueColor} flex items-center gap-2`}>
      <div className="relative">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} />
        {venue.status === "connected" && (
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
