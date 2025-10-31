import type { BacktestResult, StrategySummary } from '@/types/trading';

const BASE = '';

async function api<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json() as Promise<T>;
}

// Strategies
export const getStrategies = (signal?: AbortSignal) =>
  api<StrategySummary[]>('/api/strategies', undefined, signal);
export const getStrategy = (id: string, signal?: AbortSignal) =>
  api<StrategySummary>(`/api/strategies/${id}`, undefined, signal);
export const startStrategy = (id: string, params?: Record<string, unknown>, signal?: AbortSignal) =>
  api(`/api/strategies/${id}/start`, { method: 'POST', body: JSON.stringify({ params }) }, signal);
export const stopStrategy = (id: string, signal?: AbortSignal) =>
  api(`/api/strategies/${id}/stop`, { method: 'POST' }, signal);
export const updateStrategy = (id: string, params: Record<string, unknown>, signal?: AbortSignal) =>
  api(`/api/strategies/${id}/update`, { method: 'POST', body: JSON.stringify({ params }) }, signal);

// Backtests
export const startBacktest = (payload: {
  strategyId: string;
  params?: Record<string, unknown>;
  symbols?: string[];
  startDate: string;
  endDate: string;
  initialCapital?: number;
  feeBps?: number;
  slippageBps?: number;
}) => api<{ jobId: string }>('/api/backtests', { method: 'POST', body: JSON.stringify(payload) });

export const pollBacktest = (jobId: string, signal?: AbortSignal) =>
  api<{
    status: 'queued' | 'running' | 'done' | 'error';
    progress: number;
    result?: BacktestResult;
  }>(`/api/backtests/${jobId}`, undefined, signal);

// Dashboard
export const getDashboardSummary = (q: URLSearchParams, signal?: AbortSignal) =>
  api<{
    kpis: {
      totalPnl: number;
      winRate: number;
      sharpe: number;
      maxDrawdown: number;
      openPositions: number;
    };
    equityByStrategy: Array<{ t: string; [strategyId: string]: number }>;
    pnlBySymbol: Array<{ symbol: string; pnl: number }>;
    returns: number[];
  }>(`/api/metrics/summary?${q.toString()}`, undefined, signal);

export const getPositions = (signal?: AbortSignal) =>
  api<Array<{ symbol: string; qty: number; entry: number; mark: number; pnl: number }>>(
    '/api/positions',
    undefined,
    signal,
  );

export const getRecentTrades = (signal?: AbortSignal) =>
  api<Array<{
    time: string;
    symbol: string;
    side: 'buy' | 'sell';
    qty: number;
    price: number;
    pnl?: number;
  }>>('/api/trades/recent?limit=100', undefined, signal);

export const getAlerts = (signal?: AbortSignal) =>
  api<Array<{ time: string; level: 'info' | 'warn' | 'error'; text: string }>>(
    '/api/alerts?limit=50',
    undefined,
    signal,
  );

export const getHealth = (signal?: AbortSignal) =>
  api<{
    venues: Array<{ name: string; status: 'ok' | 'warn' | 'down'; latencyMs: number; queue: number }>;
  }>('/api/health', undefined, signal);
