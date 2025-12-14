import { LayoutDashboard, Target, Wallet, Brain, Settings, Activity, Terminal, Scan } from "lucide-react";
import { motion } from "motion/react";
import { Suspense, lazy, useEffect, useState } from "react";

import { Skeleton } from "./ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

// Lazy load tab components for better performance
const DashboardTab = lazy(() =>
  import("./tabs/DashboardTab").then((module) => ({ default: module.DashboardTab })),
);
const MLTab = lazy(() =>
  import("./tabs/MLTab").then((module) => ({ default: module.MLTab })),
);
const HealthMonitor = lazy(() =>
  import("./HealthMonitor").then((module) => ({ default: module.HealthMonitor })),
);
const StrategyTab = lazy(() =>
  import("./tabs/StrategyTab").then((module) => ({ default: module.StrategyTab })),
);
const FundingTab = lazy(() =>
  import("./tabs/FundingTab").then((module) => ({ default: module.FundingTab })),
);
const BacktestingTab = lazy(() =>
  import("./tabs/BacktestingTab").then((module) => ({ default: module.BacktestingTab })),
);
const SettingsTab = lazy(() =>
  import("./tabs/SettingsTab").then((module) => ({ default: module.SettingsTab })),
);
const MarketScannerTab = lazy(() =>
  import("./tabs/MarketScannerTab").then((module) => ({ default: module.MarketScannerTab })),
);
const LogViewerTab = lazy(() =>
  import("./tabs/LogViewerTab").then((module) => ({ default: module.LogViewerTab })),
);

export function TabbedInterface() {
  const [activeTab, setActiveTab] = useState(() => {
    const hash = window.location.hash.replace("#", "");
    return hash || "dashboard";
  });

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace("#", "");
      if (hash) setActiveTab(hash);
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    window.location.hash = value;
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.1 }}
      className="flex-1 flex flex-col border-t border-zinc-800/50 bg-zinc-900/40 backdrop-blur-sm overflow-hidden"
    >
      <Tabs value={activeTab} onValueChange={handleTabChange} className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="w-full justify-start border-b border-zinc-800/50 bg-transparent rounded-none px-8 h-12 flex-shrink-0">
          <TabsTrigger
            value="dashboard"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <LayoutDashboard className="w-4 h-4" />
            <span>Dashboard</span>
          </TabsTrigger>

          <TabsTrigger
            value="neural-link"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Brain className="w-4 h-4" />
            <span>Neural Link</span>
          </TabsTrigger>

          <TabsTrigger
            value="scanner"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Scan className="w-4 h-4" />
            <span>Scanner</span>
          </TabsTrigger>

          <TabsTrigger
            value="system-internals"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Activity className="w-4 h-4" />
            <span>System Internals</span>
          </TabsTrigger>

          <TabsTrigger
            value="logs"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Terminal className="w-4 h-4" />
            <span>System Logs</span>
          </TabsTrigger>

          <TabsTrigger
            value="strategy"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Target className="w-4 h-4" />
            <span>Strategy</span>
          </TabsTrigger>

          <TabsTrigger
            value="backtesting"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Terminal className="w-4 h-4" />
            <span>Backtesting</span>
          </TabsTrigger>

          <TabsTrigger
            value="funding"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Wallet className="w-4 h-4" />
            <span>Funding</span>
          </TabsTrigger>

          <TabsTrigger
            value="settings"
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Settings className="w-4 h-4" />
            <span>Settings</span>
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-y-auto">
          <TabsContent value="dashboard" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <DashboardTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="neural-link" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <MLTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="scanner" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <MarketScannerTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="system-internals" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <HealthMonitor />
            </Suspense>
          </TabsContent>

          <TabsContent value="logs" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <LogViewerTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="strategy" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <StrategyTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="backtesting" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <BacktestingTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="funding" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <FundingTab />
            </Suspense>
          </TabsContent>

          <TabsContent value="settings" className="m-0 h-full">
            <Suspense fallback={<TabSkeleton />}>
              <SettingsTab />
            </Suspense>
          </TabsContent>
        </div>
      </Tabs>
    </motion.div>
  );
}

function TabSkeleton() {
  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      {/* Header skeleton */}
      <div className="flex flex-wrap items-end gap-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-10 w-32" />
        <Skeleton className="h-10 w-40" />
        <Skeleton className="h-10 w-24" />
      </div>

      {/* KPI cards skeleton */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>

      {/* Charts skeleton */}
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>

      {/* Tables skeleton */}
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-64" />
        ))}
      </div>
    </div>
  );
}
