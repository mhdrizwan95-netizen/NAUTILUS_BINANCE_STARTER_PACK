"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Toaster, toast } from "sonner";
import { TopHUD } from "@/components/TopHUD";
import { StrategyMatrix } from "@/components/StrategyMatrix";
import { RightPanel } from "@/components/RightPanel";
import { BottomBar } from "@/components/BottomBar";
import { SettingsModal } from "@/components/SettingsModal";
import {
  venues,
  strategies,
  generatePerformanceData,
  generateRecentTrades,
  generateAlerts,
  getGlobalMetrics,
} from "@/lib/mockData";
import type {
  ModeType,
  StrategyPerformance,
  Strategy,
  Venue,
  GlobalSettings,
  TrendStrategyConfig,
  ScalpStrategyConfig,
  MomentumStrategyConfig,
  MemeStrategyConfig,
  ListingStrategyConfig,
  VolScannerConfig,
} from "@/lib/types";
import { Button } from "@/components/ui/button";

export default function Page() {
  const [mode, setMode] = useState<ModeType>("paper");
  const [performances, setPerformances] = useState<StrategyPerformance[]>(() => generatePerformanceData());
  const [recentTrades, setRecentTrades] = useState(() => generateRecentTrades());
  const [alerts, setAlerts] = useState(() => generateAlerts());
  const [selectedPerformance, setSelectedPerformance] = useState<StrategyPerformance | null>(null);
  const [isBooting, setIsBooting] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [globalSettings, setGlobalSettings] = useState<GlobalSettings>({
    leverageCap: 5,
    perTradePercent: 1,
    maxPositions: 25,
    dailyLossStop: 10,
    circuitBreakerEnabled: true,
    circuitBreakerThreshold: 15,
  });

  const [trendConfig, setTrendConfig] = useState<TrendStrategyConfig>({
    maLength: 50,
    rsiThreshold: 70,
    cooldownMinutes: 30,
    trailingStopPercent: 3,
  });

  const [scalpConfig, setScalpConfig] = useState<ScalpStrategyConfig>({
    spreadPercent: 0.2,
    stopPercent: 0.5,
    orderType: "limit",
    maxScalpsPerDay: 100,
  });

  const [momentumConfig, setMomentumConfig] = useState<MomentumStrategyConfig>({
    surgePercent: 5,
    trailingStopPercent: 8,
    skipPumped: true,
    lookbackMinutes: 60,
  });

  const [memeConfig, setMemeConfig] = useState<MemeStrategyConfig>({
    sentimentThreshold: 70,
    twitterEnabled: true,
    redditEnabled: true,
    telegramEnabled: false,
    sizeCap: 5000,
  });

  const [listingConfig, setListingConfig] = useState<ListingStrategyConfig>({
    autoBuy: false,
    maxSlippagePercent: 3,
    takeProfitPercent: 50,
    stopLossPercent: 30,
  });

  const [volScannerConfig, setVolScannerConfig] = useState<VolScannerConfig>({
    spikePercent: 300,
    mode: "alert",
    minVolume: 1_000_000,
  });

  const globalMetrics = useMemo(() => getGlobalMetrics(performances), [performances]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsBooting(false);
      toast.info("Nautilus Terminal Online", {
        description: "All systems operational",
      });
    }, 1500);

    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (isBooting) return;

    const interval = setInterval(() => {
      setPerformances(generatePerformanceData());
      setRecentTrades(generateRecentTrades());
      if (Math.random() > 0.7) {
        setAlerts((prev) => [generateAlerts(1)[0], ...prev.slice(0, 9)]);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [isBooting]);

  const handleModeChange = (newMode: ModeType) => {
    setMode(newMode);
    toast.success(`Switched to ${newMode.toUpperCase()} mode`, {
      description: newMode === "live" ? "Real capital at risk" : "Simulated trading active",
    });
  };

  const handleKillSwitch = () => {
    toast.error("EMERGENCY STOP ACTIVATED", {
      description: "All positions closed, trading halted",
    });
  };

  const handlePodClick = (performance: StrategyPerformance, strategy: Strategy, venue: Venue) => {
    setSelectedPerformance(performance);
  };

  if (isBooting) {
    return (
      <div className="h-screen bg-zinc-950 flex items-center justify-center">
        <Toaster theme="dark" richColors />
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center">
          <motion.div
            className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-400 via-violet-400 to-indigo-500 relative"
            animate={{
              boxShadow: [
                "0 0 20px rgba(0, 245, 212, 0.3)",
                "0 0 40px rgba(0, 245, 212, 0.5)",
                "0 0 20px rgba(0, 245, 212, 0.3)",
              ],
            }}
            transition={{ duration: 2, repeat: Infinity }}
          />
          <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="text-zinc-100 mb-2">
            NAUTILUS TERMINAL
          </motion.h1>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }} className="text-zinc-500 text-sm tracking-wider">
            INITIALIZING NEURAL NETWORK...
          </motion.p>
        </motion.div>
      </div>
    );
  }

  const selectedStrategy = selectedPerformance
    ? strategies.find((strategy) => strategy.id === selectedPerformance.strategyId) ?? null
    : null;

  const selectedVenue = selectedPerformance
    ? venues.find((venue) => venue.id === selectedPerformance.venueId) ?? null
    : null;

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col overflow-hidden">
      <Toaster theme="dark" richColors />
      <TopHUD
        mode={mode}
        onModeChange={handleModeChange}
        metrics={globalMetrics}
        venues={venues}
        onKillSwitch={handleKillSwitch}
        onSettingsClick={() => setSettingsOpen(true)}
      />

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-auto px-8 py-6 pb-24">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-zinc-200 text-lg">Strategy Command Deck</h2>
              <p className="text-xs text-zinc-500">Monitor venue health, risk and live execution signals.</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => setPerformances(generatePerformanceData())}>
              Refresh Metrics
            </Button>
          </div>

          <StrategyMatrix
            performances={performances}
            strategies={strategies}
            venues={venues}
            onSelect={handlePodClick}
          />
        </div>
        <RightPanel
          performance={selectedPerformance}
          strategy={selectedStrategy}
          venue={selectedVenue}
          trades={recentTrades}
          onClose={() => setSelectedPerformance(null)}
        />
      </div>

      <BottomBar alerts={alerts} recentTrades={recentTrades} />

      <SettingsModal
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        globalSettings={globalSettings}
        onGlobalSettingsChange={setGlobalSettings}
        trendConfig={trendConfig}
        scalpConfig={scalpConfig}
        momentumConfig={momentumConfig}
        memeConfig={memeConfig}
        listingConfig={listingConfig}
        volScannerConfig={volScannerConfig}
        onTrendConfigChange={setTrendConfig}
        onScalpConfigChange={setScalpConfig}
        onMomentumConfigChange={setMomentumConfig}
        onMemeConfigChange={setMemeConfig}
        onListingConfigChange={setListingConfig}
        onVolScannerConfigChange={setVolScannerConfig}
      />
    </div>
  );
}
