import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { TopHUD } from './components/TopHUD';
import { TabbedInterface } from './components/TabbedInterface';
import { Toaster } from './components/ui/sonner';
import { toast } from 'sonner';
import { motion } from 'motion/react';
import {
  getDashboardSummary,
  getHealth,
  setTradingEnabled,
  flattenPositions,
  updateConfig,
} from './lib/api';
import { queryClient, queryKeys } from './lib/queryClient';
import { buildSummarySearchParams } from './lib/dashboardFilters';
import { useAppStore, useDashboardFilters } from './lib/store';
import { useWebSocket } from './lib/websocket';
import { generateIdempotencyKey } from './lib/idempotency';

export default function App() {
  const [isBooting, setIsBooting] = useState(true);
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const [notifiedOnline, setNotifiedOnline] = useState(false);
  const [controlState, setControlState] = useState<'pause' | 'resume' | 'flatten' | 'kill' | null>(null);
  const opsAuth = useAppStore((state) => state.opsAuth);
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

  const confirmFlatten = () => {
    const confirmed = window.confirm(
      'Flatten will attempt to close every open position immediately. Continue?'
    );
    if (!confirmed) {
      toast.info('Flatten cancelled');
    }
    return confirmed;
  };

  const promptKillReason = () => {
    const reason = window.prompt(
      'Emergency stop requires a reason for audit logging. Enter reason to proceed:',
      ''
    );
    if (!reason || !reason.trim()) {
      toast.error('Kill switch aborted: reason required');
      return null;
    }
    const confirmed = window.confirm(
      'EMERGENCY STOP will disable trading and queue a flatten. Confirm to proceed.'
    );
    if (!confirmed) {
      toast.info('Kill switch cancelled');
      return null;
    }
    return reason.trim();
  };

  const requireOpsToken = () => {
    if (!opsAuth.token.trim()) {
      toast.error('Set an OPS API token in Settings before issuing control actions.');
      return false;
    }
    if (!opsAuth.approver.trim()) {
      toast.error('Provide an approver token (two-man rule) before issuing critical controls.');
      return false;
    }
    return true;
  };

  const buildControlOptions = (prefix: string) => ({
    token: opsAuth.token.trim(),
    actor: opsAuth.actor.trim() || undefined,
    approverToken: opsAuth.approver.trim() || undefined,
    idempotencyKey: generateIdempotencyKey(prefix),
  });

  const notifyControlError = (title: string, error: unknown) => {
    const description = error instanceof Error ? error.message : 'Unknown error';
    toast.error(title, { description });
  };

  const withControl = async (
    state: 'pause' | 'resume' | 'flatten' | 'kill',
    fn: () => Promise<void>,
  ) => {
    setControlState(state);
    try {
      await fn();
    } finally {
      setControlState(null);
    }
  };

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

  const handleModeChange = async (newMode: typeof mode) => {
    if (!requireOpsToken()) {
      return;
    }
    const previous = mode;
    try {
      await updateConfig({ DRY_RUN: newMode === 'paper' }, buildControlOptions(`mode-${newMode}`));
      setMode(newMode);
      toast.success(`Switched to ${newMode.toUpperCase()} mode`, {
        description: newMode === 'live' ? 'Real capital at risk' : 'Simulated trading active',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      toast.error('Failed to toggle trading mode', { description: message });
      setMode(previous);
    }
  };

  const handlePause = async () => {
    if (!requireOpsToken()) {
      return;
    }
    await withControl('pause', async () => {
      try {
        await setTradingEnabled(false, buildControlOptions('pause'));
        toast.warning('Trading paused', {
          description: 'All new orders halted until resume or restart.',
        });
      } catch (error) {
        notifyControlError('Failed to pause trading', error);
        throw error;
      }
    });
  };

  const handleResume = async () => {
    if (!requireOpsToken()) {
      return;
    }
    await withControl('resume', async () => {
      try {
        await setTradingEnabled(true, buildControlOptions('resume'));
        toast.success('Trading resumed', { description: 'Engines may submit new orders.' });
      } catch (error) {
        notifyControlError('Failed to resume trading', error);
        throw error;
      }
    });
  };

  const handleFlatten = async () => {
    if (!requireOpsToken()) {
      return;
    }
    if (!confirmFlatten()) {
      return;
    }
    await withControl('flatten', async () => {
      try {
        const result = await flattenPositions(buildControlOptions('flatten'));
        toast.info('Flatten request submitted', {
          description: `Attempted to close ${result.requested} positions (${result.succeeded} succeeded).`,
        });
      } catch (error) {
        notifyControlError('Flatten request failed', error);
        throw error;
      }
    });
  };

  const handleKillSwitch = async () => {
    if (!requireOpsToken()) {
      return;
    }
    const reason = promptKillReason();
    if (!reason) {
      return;
    }
    await withControl('kill', async () => {
      try {
        await setTradingEnabled(false, buildControlOptions('kill-pause'), reason);
        const result = await flattenPositions(buildControlOptions('kill-flatten'));
        toast.error('EMERGENCY STOP ACTIVATED', {
          description: `Trading disabled and flatten queued (${result.succeeded}/${result.requested}).`,
        });
      } catch (error) {
        notifyControlError('Kill switch failed', error);
        throw error;
      }
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
        onPause={handlePause}
        onResume={handleResume}
        onFlatten={handleFlatten}
        controlState={controlState}
      />

      <TabbedInterface />

      <Toaster />
    </div>
  );
}
