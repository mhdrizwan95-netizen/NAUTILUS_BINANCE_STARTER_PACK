import { QueryClient } from "@tanstack/react-query";
import type { DefaultOptions } from "@tanstack/react-query";

// Default query options for consistent behavior
const defaultQueryOptions: DefaultOptions = {
  queries: {
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: 1,
    retryDelay: 2_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    networkMode: "always",
  },
  mutations: {
    retry: 1,
    retryDelay: 1_000,
  },
};

// Create and configure the query client
export const queryClient = new QueryClient({
  defaultOptions: defaultQueryOptions,
});

// Query keys for consistent caching
export const queryKeys = {
  // Dashboard queries
  dashboard: {
    summary: (params: Record<string, unknown>) => ["dashboard", "summary", params],
    positions: () => ["dashboard", "positions"],
    trades: () => ["dashboard", "trades"],
    alerts: () => ["dashboard", "alerts"],
    health: () => ["dashboard", "health"],
  },
  // Strategy queries
  strategies: {
    list: () => ["strategies", "list"],
    detail: (id: string) => ["strategies", "detail", id],
  },
  ops: {
    status: () => ["ops", "status"],
  },
  funding: {
    portfolio: () => ["funding", "portfolio"],
    exposure: () => ["funding", "exposure"],
    pnl: () => ["funding", "pnl"],
  },
  settings: {
    config: () => ["settings", "config"],
  },
  // Backtest queries
  backtests: {
    status: (jobId: string) => ["backtests", "status", jobId],
  },
} as const;

// Mutation keys for optimistic updates
export const mutationKeys = {
  strategies: {
    start: (id: string) => ["strategies", "start", id],
    stop: (id: string) => ["strategies", "stop", id],
    update: (id: string) => ["strategies", "update", id],
  },
  backtests: {
    start: () => ["backtests", "start"],
  },
} as const;
