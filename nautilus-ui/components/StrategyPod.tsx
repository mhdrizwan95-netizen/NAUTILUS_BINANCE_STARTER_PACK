"use client";

import { memo } from "react";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from "lucide-react";
import clsx from "clsx";
import { Badge } from "@/components/ui/badge";
import { MiniChart } from "@/components/MiniChart";
import type { StrategyPerformance, Strategy, Venue } from "@/lib/types";
import { getVenueColor, getVenueGradient } from "@/lib/mockData";

interface StrategyPodProps {
  performance: StrategyPerformance;
  strategy: Strategy;
  venue: Venue;
  onClick: () => void;
}

export const StrategyPod = memo(function StrategyPod({
  performance,
  strategy,
  venue,
  onClick,
}: StrategyPodProps) {
  const { metrics, health } = performance;
  const venueColor = getVenueColor(venue.type);
  const venueGradient = getVenueGradient(venue.type);

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);

  const formatPercent = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

  const getTrendIcon = () => {
    if (metrics.pnlPercent > 1) return <TrendingUp className="w-4 h-4" />;
    if (metrics.pnlPercent < -1) return <TrendingDown className="w-4 h-4" />;
    return <Minus className="w-4 h-4" />;
  };

  const getPnLColor = () => {
    if (metrics.pnlPercent > 0) return "text-emerald-400";
    if (metrics.pnlPercent < 0) return "text-red-400";
    return "text-zinc-400";
  };

  const healthStyles = {
    optimal: "border-emerald-400/20 bg-emerald-400/5",
    warning: "border-amber-400/20 bg-amber-400/5",
    critical: "border-red-400/20 bg-red-400/5",
  }[health];

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.2 }}
      onClick={onClick}
      className={clsx(
        "relative rounded-2xl bg-zinc-900/70 backdrop-blur-xl border p-4 cursor-pointer group overflow-hidden",
        healthStyles,
      )}
    >
      <div
        className={clsx(
          "absolute inset-0 opacity-0 group-hover:opacity-5 transition-opacity duration-300 pointer-events-none",
          `bg-gradient-to-br ${venueGradient}`,
        )}
      />

      <div className="flex items-start justify-between mb-3 relative z-10">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-zinc-100">{strategy.name}</h3>
            {health === "critical" && <AlertTriangle className="w-4 h-4 text-red-400" />}
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs px-2 py-0 border-zinc-700/50 text-zinc-400">
              {venue.name}
            </Badge>
            <span className="text-xs text-zinc-600 font-mono">{metrics.tradeCount} trades</span>
          </div>
        </div>
        <div className="flex flex-col items-end">
          <div className={clsx("flex items-center gap-1", getPnLColor())}>
            {getTrendIcon()}
            <span className="font-mono">{formatPercent(metrics.pnlPercent)}</span>
          </div>
          <span className={clsx("text-xs font-mono", getPnLColor())}>{formatCurrency(metrics.pnl)}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-3 relative z-10">
        <MetricCell label="Sharpe" value={metrics.sharpe.toFixed(2)} />
        <MetricCell label="VaR" value={`${(metrics.var * 100).toFixed(1)}%`} />
        <MetricCell label="DD" value={`${(metrics.drawdown * 100).toFixed(1)}%`} />
      </div>

      <div className="h-12 mb-3 relative z-10">
        <MiniChart
          data={metrics.sparkline}
          color={venueColor}
          trend={metrics.pnlPercent > 0 ? "up" : metrics.pnlPercent < 0 ? "down" : "neutral"}
        />
      </div>

      <div className="space-y-1 relative z-10">
        {metrics.topSymbols.slice(0, 2).map((symbol, idx) => (
          <div key={idx} className="flex items-center justify-between">
            <span className="text-xs text-zinc-500 font-mono">{symbol.symbol}</span>
            <span
              className={clsx(
                "text-xs font-mono",
                symbol.pnl >= 0 ? "text-emerald-400/70" : "text-red-400/70",
              )}
            >
              {formatCurrency(symbol.pnl)}
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mt-3 pt-3 border-t border-zinc-800/50 relative z-10">
        <span className="text-xs text-zinc-600">Latency</span>
        <span className="text-xs text-zinc-400 font-mono">{metrics.latency.toFixed(0)}ms</span>
      </div>
    </motion.div>
  );
});

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-zinc-800/30 rounded-lg p-2">
      <div className="text-xs text-zinc-600 mb-0.5">{label}</div>
      <div className="text-xs text-zinc-300 font-mono">{value}</div>
    </div>
  );
}
