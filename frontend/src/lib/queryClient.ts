import { QueryClient, DefaultOptions } from '@tanstack/react-query';

// Default query options for consistent behavior
const defaultQueryOptions: DefaultOptions = {
  queries: {
    // Cache data for 5 minutes by default
    staleTime: 5 * 60 * 1000, // 5 minutes
    // Keep data in cache for 10 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes (formerly cacheTime)
    // Retry failed requests 3 times with exponential backoff
    retry: (failureCount, error) => {
      // Don't retry on 4xx errors (client errors)
      if (error instanceof Error && 'status' in error) {
        const status = (error as any).status;
        if (status >= 400 && status < 500) {
          return false;
        }
      }
      // Retry up to 3 times for other errors
      return failureCount < 3;
    },
    // Retry delay with exponential backoff
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
    // Refetch on window focus for real-time data
    refetchOnWindowFocus: true,
    // Don't refetch on reconnect by default (we'll handle this manually)
    refetchOnReconnect: false,
  },
  mutations: {
    // Retry mutations once on failure
    retry: 1,
    // Retry delay for mutations
    retryDelay: 1000,
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
    summary: (params: Record<string, any>) => ['dashboard', 'summary', params],
    positions: () => ['dashboard', 'positions'],
    trades: () => ['dashboard', 'trades'],
    alerts: () => ['dashboard', 'alerts'],
    health: () => ['dashboard', 'health'],
  },
  // Strategy queries
  strategies: {
    list: () => ['strategies', 'list'],
    detail: (id: string) => ['strategies', 'detail', id],
  },
  ops: {
    status: () => ['ops', 'status'],
  },
  funding: {
    portfolio: () => ['funding', 'portfolio'],
    exposure: () => ['funding', 'exposure'],
    pnl: () => ['funding', 'pnl'],
  },
  settings: {
    config: () => ['settings', 'config'],
  },
  // Backtest queries
  backtests: {
    status: (jobId: string) => ['backtests', 'status', jobId],
  },
} as const;

// Mutation keys for optimistic updates
export const mutationKeys = {
  strategies: {
    start: (id: string) => ['strategies', 'start', id],
    stop: (id: string) => ['strategies', 'stop', id],
    update: (id: string) => ['strategies', 'update', id],
  },
  backtests: {
    start: () => ['backtests', 'start'],
  },
} as const;
