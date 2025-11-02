import type {
  BacktestResult,
  StrategySummary,
  PortfolioAggregate,
  ExposureAggregate,
  PnlSnapshot,
  Trade,
  Alert,
} from '@/types/trading';
import type { ConfigEffective } from './validation';

const BASE = '';

const DEFAULT_TIMEOUT_MS = 10_000;

interface TimeoutSignal {
  signal: AbortSignal;
  cleanup: () => void;
}

const createTimeoutSignal = (signal?: AbortSignal, timeoutMs: number = DEFAULT_TIMEOUT_MS): TimeoutSignal => {
  if (signal?.aborted) {
    return { signal, cleanup: () => {} };
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort(new DOMException(`Request timed out after ${timeoutMs}ms`, 'TimeoutError'));
  }, timeoutMs);

  let relayAbort: (() => void) | undefined;

  if (signal) {
    relayAbort = () => {
      controller.abort(signal.reason);
    };
    signal.addEventListener('abort', relayAbort, { once: true });
  }

  const cleanup = () => {
    window.clearTimeout(timeoutId);
    if (signal && relayAbort) {
      signal.removeEventListener('abort', relayAbort);
    }
  };

  return { signal: controller.signal, cleanup };
};

async function api<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const { signal: timeoutSignal, cleanup } = createTimeoutSignal(signal);

  try {
    const response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      signal: timeoutSignal,
    });

    if (!response.ok) {
      const body = await response.text();
      const error = new Error(body || `Request to ${path} failed with ${response.status}`);
      (error as Error & { status?: number }).status = response.status;
      throw error;
    }

    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error(`Request to ${path} timed out after ${DEFAULT_TIMEOUT_MS}ms`);
    }
    throw error;
  } finally {
    cleanup();
  }
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
  api<Trade[]>('/api/trades/recent?limit=100', undefined, signal);

export const getAlerts = (signal?: AbortSignal) =>
  api<Alert[]>('/api/alerts?limit=50', undefined, signal);

export const getHealth = (signal?: AbortSignal) =>
  api<{
    venues: Array<{ name: string; status: 'ok' | 'warn' | 'down'; latencyMs: number; queue: number }>;
  }>('/api/health', undefined, signal);

// Aggregated portfolio & exposure
export const getAggregatePortfolio = (signal?: AbortSignal) =>
  api<PortfolioAggregate>('/aggregate/portfolio', undefined, signal);

export const getAggregateExposure = (signal?: AbortSignal) =>
  api<ExposureAggregate>('/aggregate/exposure', undefined, signal);

export const getAggregatePnl = (signal?: AbortSignal) =>
  api<PnlSnapshot>('/aggregate/pnl', undefined, signal);

// Config
export const getConfigEffective = (signal?: AbortSignal) =>
  api<ConfigEffective>('/api/config/effective', undefined, signal);

export const updateConfig = (
  payload: Record<string, unknown>,
  token: string,
  signal?: AbortSignal,
) =>
  api<ConfigEffective>(
    '/api/config',
    {
      method: 'PUT',
      body: JSON.stringify(payload),
      headers: {
        'X-Ops-Token': token,
      },
    },
    signal,
  );
