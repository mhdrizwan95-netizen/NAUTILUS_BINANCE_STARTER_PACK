import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { toast } from "sonner";

import { TabbedInterface } from "./components/TabbedInterface";
import { TopHUD } from "./components/TopHUD";
import { Toaster } from "./components/ui/sonner";
import {
  flattenPositions,
  getConfigEffective,
  getDashboardSummary,
  getHealth,
  getOpsStatus,
  setTradingEnabled,
  updateConfig,
} from "./lib/api";
import { buildSummarySearchParams } from "./lib/dashboardFilters";
import { useRenderCounter } from "./lib/debug/why";
import { stableHash } from "./lib/equality";
import { generateIdempotencyKey } from "./lib/idempotency";
import { LoopGuard } from "./lib/loopGuard";
import { queryClient, queryKeys } from "./lib/queryClient";
import { useAppStore, useDashboardFilters } from "./lib/store";
import { mergeMetricsSnapshot, mergeVenuesSnapshot } from "./lib/streamMergers";
import { useWebSocket } from "./lib/websocket";

type DashboardSummarySnapshot = Awaited<ReturnType<typeof getDashboardSummary>>;
type HealthSnapshot = Awaited<ReturnType<typeof getHealth>>;

const BOOT_TIMEOUT_MS = 10_000;

type BootPhase = "booting" | "ready" | "degraded";

type BootStatus = {
  phase: BootPhase;
  note?: string | null;
};

type ShellProps = {
  bootStatus: BootStatus;
  summaryParamsKey: string;
  setBootStatus: Dispatch<SetStateAction<BootStatus>>;
};

const scheduleTask = (cb: () => void) => {
  if (typeof queueMicrotask === "function") {
    queueMicrotask(cb);
  } else {
    void Promise.resolve().then(cb);
  }
};

const isMetricPayload = (value: unknown): value is Record<string, number> =>
  typeof value === "object" &&
  value !== null &&
  Object.values(value).every((entry) => typeof entry === "number");

const sanitizeVenues = (value: unknown): Array<Record<string, unknown>> => {
  if (Array.isArray(value)) {
    return value.filter(
      (entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null,
    );
  }
  if (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { venues?: unknown }).venues)
  ) {
    return ((value as { venues?: unknown }).venues as unknown[]).filter(
      (entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null,
    );
  }
  return [];
};

export function App() {
  useRenderCounter("App");
  const [bootStatus, setBootStatus] = useState<BootStatus>({ phase: "booting", note: null });
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
  const healthQueryKey = useMemo(() => queryKeys.dashboard.health(), []);
  const summaryQueryKeyRef = useRef(summaryQueryKey);
  const healthQueryKeyRef = useRef(healthQueryKey);
  summaryQueryKeyRef.current = summaryQueryKey;
  healthQueryKeyRef.current = healthQueryKey;
  const bootResolvedRef = useRef(false);
  const bootFetchInFlightRef = useRef(false);

  useEffect(() => {
    if (bootResolvedRef.current || bootFetchInFlightRef.current) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const paramsForBoot = new URLSearchParams(summaryParamsKey);
    bootFetchInFlightRef.current = true;

    const hydrateBootData = async () => {
      const [summaryResult, healthResult] = await Promise.allSettled([
        getDashboardSummary(paramsForBoot, controller.signal),
        getHealth(controller.signal),
      ]);
      if (cancelled) {
        return;
      }
      if (summaryResult.status === "fulfilled") {
        queryClient.setQueryData(summaryQueryKeyRef.current, summaryResult.value);
      }
      if (healthResult.status === "fulfilled") {
        queryClient.setQueryData(healthQueryKeyRef.current, healthResult.value);
      }
      bootResolvedRef.current = true;
      const summaryError =
        summaryResult.status === "rejected" && summaryResult.reason instanceof Error
          ? summaryResult.reason
          : null;
      const healthError =
        healthResult.status === "rejected" && healthResult.reason instanceof Error
          ? healthResult.reason
          : null;
      const note = summaryError?.message ?? healthError?.message ?? null;
      setBootStatus({
        phase:
          summaryResult.status === "fulfilled" && healthResult.status === "fulfilled"
            ? "ready"
            : "degraded",
        note,
      });
    };

    hydrateBootData()
      .catch((error) => {
        if (cancelled) {
          return;
        }
        bootResolvedRef.current = true;
        setBootStatus({
          phase: "degraded",
          note: error instanceof Error ? error.message : "Boot fetch failed",
        });
      })
      .finally(() => {
        bootFetchInFlightRef.current = false;
      });

    return () => {
      cancelled = true;
      bootFetchInFlightRef.current = false;
      controller.abort();
    };
  }, [summaryParamsKey]);

  useEffect(() => {
    if (bootResolvedRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      if (bootResolvedRef.current) {
        return;
      }
      bootResolvedRef.current = true;
      setBootStatus({
        phase: "degraded",
        note: "Boot timeout — continuing in degraded mode",
      });
    }, BOOT_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, []);

  if (bootStatus.phase === "booting") {
    return (
      <div className="h-screen bg-zinc-950 flex items-center justify-center">
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
    <CommandCenterShell
      bootStatus={bootStatus}
      summaryParamsKey={summaryParamsKey}
      setBootStatus={setBootStatus}
    />
  );
}

function CommandCenterShell({ bootStatus, summaryParamsKey, setBootStatus }: ShellProps) {
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const [notifiedOnline, setNotifiedOnline] = useState(false);
  const [controlState, setControlState] = useState<"pause" | "resume" | "flatten" | "kill" | null>(
    null,
  );
  const opsToken = useAppStore((state) => state.opsAuth.token);
  const opsActor = useAppStore((state) => state.opsAuth.actor);
  // TEMP DEBUG
  const { lastMessage, isConnected: wsConnected } = useWebSocket();
  const lastProcessedMessage = useRef<{ type: string; ts: number | null } | null>(null);
  const metricsDigestRef = useRef<string | null>(null);
  const venuesDigestRef = useRef<string | null>(null);

  const summaryParams = useMemo(() => new URLSearchParams(summaryParamsKey), [summaryParamsKey]);
  const summaryQueryKey = useMemo(
    () => queryKeys.dashboard.summary({ params: summaryParamsKey }),
    [summaryParamsKey],
  );
  const fetchDashboardSummary = useCallback(
    () => getDashboardSummary(summaryParams),
    [summaryParams],
  );
  const summaryQueryOptions = useMemo(
    () => ({
      queryKey: summaryQueryKey,
      queryFn: fetchDashboardSummary,
      staleTime: 30 * 1000,
    }),
    [summaryQueryKey, fetchDashboardSummary],
  );
  const summaryQuery = useQuery(summaryQueryOptions);

  const configQueryKey = useMemo(() => queryKeys.settings.config(), []);
  const fetchConfig = useCallback(() => getConfigEffective(), []);
  const configQueryOptions = useMemo(
    () => ({
      queryKey: configQueryKey,
      queryFn: fetchConfig,
      staleTime: 60 * 1000,
    }),
    [configQueryKey, fetchConfig],
  );
  const configQuery = useQuery(configQueryOptions);

  const opsStatusQueryKey = useMemo(() => queryKeys.ops.status(), []);
  const fetchOpsStatus = useCallback(() => getOpsStatus(), []);
  const opsStatusQueryOptions = useMemo(
    () => ({
      queryKey: opsStatusQueryKey,
      queryFn: fetchOpsStatus,
      refetchInterval: 15 * 1000,
    }),
    [opsStatusQueryKey, fetchOpsStatus],
  );
  const opsStatusQuery = useQuery(opsStatusQueryOptions);

  const healthQueryKey = useMemo(() => queryKeys.dashboard.health(), []);
  const fetchHealth = useCallback(() => getHealth(), []);
  const healthQueryOptions = useMemo(
    () => ({
      queryKey: healthQueryKey,
      queryFn: fetchHealth,
      staleTime: 30 * 1000,
    }),
    [healthQueryKey, fetchHealth],
  );
  const healthQuery = useQuery(healthQueryOptions);

  const renderGuardRef = useRef<LoopGuard | null>(null);
  if (!renderGuardRef.current) {
    renderGuardRef.current = new LoopGuard({
      maxIter: 500,
      timeoutMs: 5_000,
      sampleEvery: 5,
      name: "App render",
    });
  }

  useEffect(() => {
    renderGuardRef.current?.reset();
  }, [summaryQuery.status, healthQuery.status]);

  useEffect(() => {
    if (!notifiedOnline && summaryQuery.isSuccess) {
      toast.info("Nautilus Terminal Online", {
        description: "All systems operational",
      });
      setNotifiedOnline(true);
    }
  }, [notifiedOnline, summaryQuery.isSuccess]);

  const configDerivedMode = useMemo(() => {
    const effective = configQuery.data?.effective as Record<string, unknown> | undefined;
    const overrides = configQuery.data?.overrides as Record<string, unknown> | undefined;
    const dryRunValue = (effective?.DRY_RUN ?? overrides?.DRY_RUN) as unknown;
    if (typeof dryRunValue === "boolean") {
      return dryRunValue ? "paper" : "live";
    }
    return null;
  }, [configQuery.data]);

  useEffect(() => {
    if (!configDerivedMode) {
      return;
    }
    setMode((prev) => (prev === configDerivedMode ? prev : configDerivedMode));
  }, [configDerivedMode]);

  const handleRecovery = useCallback(() => {
    setBootStatus((prev) => (prev.phase === "ready" ? prev : { phase: "ready", note: prev.note }));
  }, [setBootStatus]);

  useEffect(() => {
    if (bootStatus.phase !== "degraded") {
      return;
    }
    if (summaryQuery.status === "success" && healthQuery.status === "success") {
      handleRecovery();
    }
  }, [bootStatus.phase, summaryQuery.status, healthQuery.status, handleRecovery]);

  const tradingEnabled = (() => {
    const value = opsStatusQuery.data?.state?.trading_enabled;
    return typeof value === "boolean" ? value : true;
  })();

  const renderState = {
    bootPhase: bootStatus.phase,
    summaryStatus: summaryQuery.status,
    healthStatus: healthQuery.status,
    opsStatus: tradingEnabled,
    wsConnected,
  };
  renderGuardRef.current.tick(renderState);

  useEffect(() => {
    if (!lastMessage) {
      return;
    }

    const nextToken = {
      type: lastMessage.type,
      ts: typeof lastMessage.timestamp === "number" ? lastMessage.timestamp : null,
    };
    if (
      lastProcessedMessage.current &&
      lastProcessedMessage.current.type === nextToken.type &&
      lastProcessedMessage.current.ts === nextToken.ts
    ) {
      return;
    }
    lastProcessedMessage.current = nextToken;

    if (lastMessage.type === "metrics") {
      const data = lastMessage.data;
      const payloadCandidate =
        typeof data === "object" && data !== null && "kpis" in data
          ? (data as { kpis?: unknown }).kpis
          : data;
      if (!isMetricPayload(payloadCandidate)) {
        return;
      }
      const digest = stableHash(payloadCandidate);
      if (metricsDigestRef.current === digest) {
        return;
      }
      metricsDigestRef.current = digest;
      scheduleTask(() => {
        const current = queryClient.getQueryData<DashboardSummarySnapshot>(summaryQueryKey);
        const merged = mergeMetricsSnapshot(current, payloadCandidate);
        if (merged !== current) {
          queryClient.setQueryData(summaryQueryKey, merged);
        }
      });
    }

    if (lastMessage.type === "venues" || lastMessage.type === "health") {
      const venues = sanitizeVenues(lastMessage.data);
      const digest = stableHash(venues);
      if (venuesDigestRef.current === digest) {
        return;
      }
      venuesDigestRef.current = digest;
      scheduleTask(() => {
        const current = queryClient.getQueryData<HealthSnapshot>(healthQueryKey);
        const merged = mergeVenuesSnapshot(current, venues);
        if (merged !== current) {
          queryClient.setQueryData(healthQueryKey, merged);
        }
      });
    }
  }, [lastMessage, summaryQueryKey, healthQueryKey]);

  const confirmFlatten = () => {
    const confirmed = window.confirm(
      "Flatten will attempt to close every open position immediately. Continue?",
    );
    if (!confirmed) {
      toast.info("Flatten cancelled");
    }
    return confirmed;
  };

  const promptFlattenReason = () => {
    const reason = window.prompt(
      "Provide a reason for the flatten request (required for audit logging):",
      "",
    );
    if (!reason || !reason.trim()) {
      toast.info("Flatten cancelled: reason required");
      return null;
    }
    return reason.trim();
  };

  const promptKillReason = () => {
    const reason = window.prompt(
      "Emergency stop requires a reason for audit logging. Enter reason to proceed:",
      "",
    );
    if (!reason || !reason.trim()) {
      toast.error("Kill switch aborted: reason required");
      return null;
    }
    const confirmed = window.confirm(
      "EMERGENCY STOP will disable trading and queue a flatten. Confirm to proceed.",
    );
    if (!confirmed) {
      toast.info("Kill switch cancelled");
      return null;
    }
    return reason.trim();
  };

  const requireOpsToken = () => {
    if (!opsToken.trim()) {
      toast.error("Set an OPS API token in Settings before issuing control actions.");
      return false;
    }
    if (!opsActor.trim()) {
      toast.error(
        "Provide an operator call-sign for the audit log before issuing control actions.",
      );
      return false;
    }
    return true;
  };

  const buildControlOptions = (prefix: string) => {
    const token = opsToken.trim();
    const actor = opsActor.trim();
    return {
      token,
      actor,
      idempotencyKey: generateIdempotencyKey(prefix),
    };
  };

  const notifyControlError = (title: string, error: unknown) => {
    const description = error instanceof Error ? error.message : "Unknown error";
    toast.error(title, { description });
  };

  const withControl = async (
    state: "pause" | "resume" | "flatten" | "kill",
    fn: () => Promise<void>,
  ) => {
    setControlState(state);
    try {
      await fn();
    } finally {
      setControlState(null);
    }
  };

  const handleModeChange = async (newMode: typeof mode) => {
    if (!requireOpsToken()) {
      return;
    }
    if (newMode === "live") {
      const acknowledged = window.confirm(
        "Switching to LIVE mode will disable dry-run safeguards and place real orders. Confirm to proceed.",
      );
      if (!acknowledged) {
        toast.info("Live mode unchanged", {
          description: "Dry-run remains enabled until an operator confirms the switch.",
        });
        return;
      }
    }
    const previous = mode;
    try {
      await updateConfig({ DRY_RUN: newMode === "paper" }, buildControlOptions(`mode-${newMode}`));
      await queryClient.invalidateQueries({ queryKey: configQueryKey });
      setMode(newMode);
      toast.success(`Switched to ${newMode.toUpperCase()} mode`, {
        description: newMode === "live" ? "Real capital at risk" : "Simulated trading active",
      });
    } catch (error) {
      setMode(previous);
      notifyControlError("Failed to toggle trading mode", error);
      throw error;
    }
  };

  const handlePause = async () => {
    if (!requireOpsToken()) {
      return;
    }
    await withControl("pause", async () => {
      try {
        await setTradingEnabled(false, buildControlOptions("pause"));
        await queryClient.invalidateQueries({ queryKey: opsStatusQueryKey });
        toast.warning("Trading paused", {
          description: "Engines will stop submitting new orders.",
        });
      } catch (error) {
        notifyControlError("Failed to pause trading", error);
        throw error;
      }
    });
  };

  const handleResume = async () => {
    if (!requireOpsToken()) {
      return;
    }
    await withControl("resume", async () => {
      try {
        await setTradingEnabled(true, buildControlOptions("resume"));
        await queryClient.invalidateQueries({ queryKey: opsStatusQueryKey });
        toast.success("Trading resumed", { description: "Engines may submit new orders." });
      } catch (error) {
        notifyControlError("Failed to resume trading", error);
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
    const reason = promptFlattenReason();
    if (!reason) {
      return;
    }
    await withControl("flatten", async () => {
      try {
        const result = await flattenPositions(buildControlOptions("flatten"), reason);
        toast.info("Flatten request submitted", {
          description: `Attempted to close ${result.requested} positions (${result.succeeded} succeeded).`,
        });
      } catch (error) {
        notifyControlError("Flatten request failed", error);
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
    await withControl("kill", async () => {
      try {
        await setTradingEnabled(false, buildControlOptions("kill-pause"), reason);
        await queryClient.invalidateQueries({ queryKey: opsStatusQueryKey });
        const result = await flattenPositions(buildControlOptions("kill-flatten"), reason);
        toast.error("EMERGENCY STOP ACTIVATED", {
          description: `Trading disabled and flatten queued (${result.succeeded}/${result.requested}).`,
        });
      } catch (error) {
        notifyControlError("Kill switch failed", error);
        throw error;
      }
    });
  };

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
      ? venueStatuses.some((venue) => venue.status !== "down")
      : false;
  const isRealtimeConnected = wsConnected || hasHealthyVenue;

  return (
    <div className="h-screen bg-zinc-950 flex flex-col overflow-hidden dark">
      {bootStatus.phase === "degraded" ? (
        <div className="bg-amber-500/10 border-b border-amber-500/40 text-amber-200 text-sm px-4 py-2">
          Running in degraded mode{bootStatus.note ? ` — ${bootStatus.note}` : ""}
        </div>
      ) : null}
      <TopHUD
        mode={mode}
        metrics={hudMetrics}
        venues={venueStatuses}
        isConnected={isRealtimeConnected}
        isLoading={summaryQuery.isLoading || healthQuery.isLoading}
        tradingEnabled={tradingEnabled}
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
