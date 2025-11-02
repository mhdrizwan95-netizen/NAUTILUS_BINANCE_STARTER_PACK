import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { TopHUD } from './components/TopHUD';
import { TabbedInterface } from './components/TabbedInterface';
import { Toaster } from './components/ui/sonner';
import { toast } from 'sonner';
import { motion } from 'motion/react';
import { getDashboardSummary, getHealth } from './lib/api';
import { queryClient, queryKeys } from './lib/queryClient';
import { buildSummarySearchParams } from './lib/dashboardFilters';
import { useDashboardFilters } from './lib/store';
import { useWebSocket } from './lib/websocket';

export default function App() {
  const [isBooting, setIsBooting] = useState(true);
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const [notifiedOnline, setNotifiedOnline] = useState(false);
  const dashboardFilters = useDashboardFilters();
  const summaryParams = useMemo(
    () => buildSummarySearchParams(dashboardFilters),
    [dashboardFilters],
  );
  const summaryParamsKey = useMemo(() => summaryParams.toString(), [summaryParams]);
  const summaryQueryKey = useMemo(
    () => queryKeys.dashboard.summary({ params: summaryParamsKey }),
    [summaryParamsKey],
  );
  const { lastMessage, isConnected: wsConnected } = useWebSocket();

  const summaryQuery = useQuery({
    queryKey: summaryQueryKey,
    queryFn: () => getDashboardSummary(summaryParams),
    staleTime: 30 * 1000,
  });

  const healthQueryKey = queryKeys.dashboard.health();
  const healthQuery = useQuery({
    queryKey: healthQueryKey,
    queryFn: () => getHealth(),
    staleTime: 30 * 1000,
  });

  useEffect(() => {
    const timer = window.setTimeout(() => setIsBooting(false), 1200);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!summaryQuery.isLoading && !healthQuery.isLoading) {
      setIsBooting(false);
    }
  }, [summaryQuery.isLoading, healthQuery.isLoading]);

  useEffect(() => {
    if (!notifiedOnline && summaryQuery.isSuccess) {
      toast.info('Nautilus Terminal Online', {
        description: 'All systems operational',
      });
      setNotifiedOnline(true);
    }
  }, [notifiedOnline, summaryQuery.isSuccess]);

  const hudMetrics = summaryQuery.data
    ? {
        totalPnl: summaryQuery.data.kpis.totalPnl,
        winRate: summaryQuery.data.kpis.winRate,
        sharpe: summaryQuery.data.kpis.sharpe,
        maxDrawdown: summaryQuery.data.kpis.maxDrawdown,
        openPositions: summaryQuery.data.kpis.openPositions,
      }
    : null;

  const venueStatuses = healthQuery.data?.venues ?? null;
  const hasHealthyVenue =
    venueStatuses && venueStatuses.length > 0
      ? venueStatuses.some((venue) => venue.status !== 'down')
      : false;
  const isRealtimeConnected = wsConnected || hasHealthyVenue;

  useEffect(() => {
    if (!lastMessage) {
      return;
    }

    if (lastMessage.type === 'metrics') {
      const payload = lastMessage.data?.kpis ?? lastMessage.data;
      if (payload) {
        window.setTimeout(() => {
          queryClient.setQueryData(summaryQueryKey, (existing: any) => {
            if (!existing) {
              return {
                kpis: payload,
                equityByStrategy: [],
                pnlBySymbol: [],
                returns: [],
              };
            }
            return {
              ...existing,
              kpis: {
                ...existing.kpis,
                ...payload,
              },
            };
          });
        }, 0);
      }
    }

    if (lastMessage.type === 'venues' || lastMessage.type === 'health') {
      const venues = Array.isArray(lastMessage.data)
        ? lastMessage.data
        : lastMessage.data?.venues ?? [];
      window.setTimeout(() => {
        queryClient.setQueryData(healthQueryKey, { venues });
      }, 0);
    }
  }, [lastMessage, summaryQueryKey, healthQueryKey]);

  const handleModeChange = (newMode: typeof mode) => {
    setMode(newMode);
    toast.success(`Switched to ${newMode.toUpperCase()} mode`, {
      description: newMode === 'live' ? 'Real capital at risk' : 'Simulated trading active',
    });
  };

  const handleKillSwitch = () => {
    toast.error('EMERGENCY STOP ACTIVATED', {
      description: 'All positions closed, trading halted',
    });
  };

  if (isBooting) {
    return (
      <div className="h-screen bg-zinc-950 flex items-center justify-center">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center">
          <motion.div
            className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-400 via-violet-400 to-indigo-500 relative"
            animate={{
              boxShadow: [
                '0 0 20px rgba(0, 245, 212, 0.3)',
                '0 0 40px rgba(0, 245, 212, 0.5)',
                '0 0 20px rgba(0, 245, 212, 0.3)',
              ],
            }}
            transition={{ duration: 2, repeat: Infinity }}
          />
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="text-zinc-100 mb-2"
          >
            NAUTILUS TERMINAL
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
            className="text-zinc-500 text-sm tracking-wider"
          >
            INITIALIZING NEURAL NETWORK...
          </motion.p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-zinc-950 flex flex-col overflow-hidden dark">
      <TopHUD
        mode={mode}
        metrics={hudMetrics}
        venues={venueStatuses}
        isConnected={isRealtimeConnected}
        isLoading={summaryQuery.isLoading || healthQuery.isLoading}
        onModeChange={handleModeChange}
        onKillSwitch={handleKillSwitch}
      />

      <TabbedInterface />

      <Toaster />
    </div>
  );
}
