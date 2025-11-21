import type {
  BacktestResult,
  StrategySummary,
  PortfolioAggregate,
  ExposureAggregate,
  PnlSnapshot,
  Trade,
  Alert,
  Order,
  MetricsModel,
} from "@/types/trading";

import { withTimeout } from "./net/withTimeout";
import type { ConfigEffective } from "./validation";

export interface ControlRequestOptions {
  signal?: AbortSignal;
  token?: string;
  actor?: string;
  idempotencyKey?: string;
}

const BASE = "";

const DEFAULT_TIMEOUT_MS = 10_000;
const BOOT_QUERY_TIMEOUT_MS = 8_000;
const API_VERSION = "v1";

export interface FetchPageOptions {
  cursor?: string;
  limit?: number;
  signal?: AbortSignal;
}

export type FetchStrategiesOptions = FetchPageOptions;

interface TimeoutSignal {
  signal: AbortSignal;
  cleanup: () => void;
}

const createTimeoutSignal = (signal: AbortSignal | undefined, timeoutMs: number): TimeoutSignal => {
  if (signal?.aborted) {
    return { signal, cleanup: () => {} };
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort(new DOMException(`Request timed out after ${timeoutMs}ms`, "TimeoutError"));
  }, timeoutMs);

  let relayAbort: (() => void) | undefined;

  if (signal) {
    relayAbort = () => {
      controller.abort(signal.reason);
    };
    signal.addEventListener("abort", relayAbort, { once: true });
  }

  const cleanup = () => {
    window.clearTimeout(timeoutId);
    if (signal && relayAbort) {
      signal.removeEventListener("abort", relayAbort);
    }
  };

  return { signal: controller.signal, cleanup };
};

async function api<T>(
  path: string,
  init?: RequestInit,
  signal?: AbortSignal,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const { signal: timeoutSignal, cleanup } = createTimeoutSignal(signal, timeoutMs);

  const request = fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Version": API_VERSION,
      ...(init?.headers ?? {}),
    },
    signal: timeoutSignal,
  }).then(async (response) => {
    if (!response.ok) {
      let message = `Request to ${path} failed with ${response.status}`;
      let code: string | undefined;
      let details: unknown;
      let requestId: string | undefined;
      try {
        const body = await response.json();
        if (body?.error) {
          code = body.error.code;
          message = body.error.message ?? message;
          details = body.error.details;
          requestId = body.error.requestId;
        } else if (body) {
          message = JSON.stringify(body);
        }
      } catch {
        const fallback = await response.text();
        if (fallback) {
          message = fallback;
        }
      }

      const error = new Error(message) as Error & {
        status?: number;
        code?: string;
        details?: unknown;
        requestId?: string;
      };
      error.status = response.status;
      if (code) error.code = code;
      if (details !== undefined) error.details = details;
      if (requestId) error.requestId = requestId;
      throw error;
    }

    return response.json() as Promise<T>;
  });

  try {
    return await withTimeout(request, timeoutMs, path);
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error(`Request to ${path} timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    cleanup();
  }
}

const buildControlHeaders = (options?: ControlRequestOptions): Record<string, string> => {
  const headers: Record<string, string> = {};
  if (options?.token) {
    headers["X-Ops-Token"] = options.token;
  }
  if (options?.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  if (options?.actor) {
    headers["X-Ops-Actor"] = options.actor;
  }
  return headers;
};

const buildPageQuery = (options?: FetchPageOptions): URLSearchParams => {
  const params = new URLSearchParams();
  if (options?.cursor) {
    params.set("cursor", options.cursor);
  }
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  return params;
};

export interface PageMetadata {
  nextCursor: string | null;
  prevCursor: string | null;
  limit: number;
  totalHint?: number | null;
  hasMore?: boolean;
}

export interface PageResponse<T> {
  data: T[];
  page: PageMetadata;
}

// Strategies
export const getStrategies = (options?: FetchStrategiesOptions) => {
  const params = buildPageQuery(options);
  const query = params.toString();
  const path = query ? `/api/strategies?${query}` : "/api/strategies";
  return api<PageResponse<StrategySummary>>(path, undefined, options?.signal);
};
export const getStrategy = (id: string, signal?: AbortSignal) =>
  api<StrategySummary>(`/api/strategies/${id}`, undefined, signal);
export const startStrategy = (
  id: string,
  params?: Record<string, unknown>,
  options?: ControlRequestOptions,
) =>
  api(
    `/api/strategies/${id}/start`,
    { method: "POST", body: JSON.stringify({ params }), headers: buildControlHeaders(options) },
    options?.signal,
  );
export const stopStrategy = (id: string, options?: ControlRequestOptions) =>
  api(
    `/api/strategies/${id}/stop`,
    { method: "POST", headers: buildControlHeaders(options) },
    options?.signal,
  );
export const updateStrategy = (
  id: string,
  params: Record<string, unknown>,
  options?: ControlRequestOptions,
) =>
  api(
    `/api/strategies/${id}/update`,
    { method: "POST", body: JSON.stringify({ params }), headers: buildControlHeaders(options) },
    options?.signal,
  );

// Backtests
export const startBacktest = (
  payload: {
    strategyId: string;
    params?: Record<string, unknown>;
    symbols?: string[];
    startDate: string;
    endDate: string;
    initialCapital?: number;
    feeBps?: number;
    slippageBps?: number;
  },
  options?: ControlRequestOptions,
) =>
  api<{ jobId: string }>(
    "/api/backtests",
    { method: "POST", body: JSON.stringify(payload), headers: buildControlHeaders(options) },
    options?.signal,
  );

export const pollBacktest = (jobId: string, signal?: AbortSignal) =>
  api<{
    status: "queued" | "running" | "done" | "error";
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
    equityByStrategy: Array<{ t: string } & Record<string, number | string>>;
    pnlBySymbol: Array<{ symbol: string; pnl: number }>;
    returns: number[];
  }>(`/api/metrics/summary?${q.toString()}`, undefined, signal, BOOT_QUERY_TIMEOUT_MS);

export const getPositions = (options?: FetchPageOptions) => {
  const params = buildPageQuery(options);
  const query = params.toString();
  const path = query ? `/api/positions?${query}` : "/api/positions";
  return api<
    PageResponse<{ symbol: string; qty: number; entry: number; mark: number; pnl: number }>
  >(path, undefined, options?.signal);
};

export const getRecentTrades = (options?: FetchPageOptions) => {
  const params = buildPageQuery({ limit: options?.limit ?? 100, cursor: options?.cursor });
  const query = params.toString();
  const path = query ? `/api/trades/recent?${query}` : "/api/trades/recent";
  return api<PageResponse<Trade>>(path, undefined, options?.signal);
};

export const getAlerts = (options?: FetchPageOptions) => {
  const params = buildPageQuery({ limit: options?.limit ?? 50, cursor: options?.cursor });
  const query = params.toString();
  const path = query ? `/api/alerts?${query}` : "/api/alerts";
  return api<PageResponse<Alert>>(path, undefined, options?.signal);
};

export const getOpenOrders = (options?: FetchPageOptions) => {
  const params = buildPageQuery({ cursor: options?.cursor, limit: options?.limit ?? 100 });
  const query = params.toString();
  const path = query ? `/api/orders/open?${query}` : "/api/orders/open";
  return api<PageResponse<Order>>(path, undefined, options?.signal);
};

export const getMetricsModels = (options?: FetchPageOptions) => {
  const params = buildPageQuery({ cursor: options?.cursor, limit: options?.limit ?? 50 });
  const query = params.toString();
  const path = query ? `/api/metrics/models?${query}` : "/api/metrics/models";
  return api<PageResponse<MetricsModel>>(path, undefined, options?.signal);
};

export const getHealth = (signal?: AbortSignal) =>
  api<{
    venues: Array<{
      name: string;
      status: "ok" | "warn" | "down";
      latencyMs: number;
      queue: number;
    }>;
  }>("/api/health", undefined, signal, BOOT_QUERY_TIMEOUT_MS);

// Aggregated portfolio & exposure
export const getAggregatePortfolio = (signal?: AbortSignal) =>
  api<PortfolioAggregate>("/aggregate/portfolio", undefined, signal);

export const getAggregateExposure = (signal?: AbortSignal) =>
  api<ExposureAggregate>("/aggregate/exposure", undefined, signal);

export const getAggregatePnl = (signal?: AbortSignal) =>
  api<PnlSnapshot>("/aggregate/pnl", undefined, signal);

export const getOpsStatus = (signal?: AbortSignal) =>
  api<{ ok: boolean; state: { trading_enabled?: boolean } & Record<string, unknown> }>(
    "/status",
    undefined,
    signal,
  );

// Config
export const getConfigEffective = (signal?: AbortSignal) =>
  api<ConfigEffective>("/api/config/effective", undefined, signal);

export const updateConfig = (payload: Record<string, unknown>, options: ControlRequestOptions) =>
  api<ConfigEffective>(
    "/api/config",
    {
      method: "PUT",
      body: JSON.stringify(payload),
      headers: buildControlHeaders(options),
    },
    options?.signal,
  );

export const setTradingEnabled = (
  enabled: boolean,
  options: ControlRequestOptions,
  reason?: string,
) =>
  api<{ trading_enabled: boolean; ts: number }>(
    "/api/ops/kill-switch",
    {
      method: "POST",
      body: JSON.stringify(
        reason && reason.trim() ? { enabled, reason: reason.trim() } : { enabled },
      ),
      headers: buildControlHeaders(options),
    },
    options?.signal,
  );

export const flattenPositions = (options: ControlRequestOptions, reason: string) =>
  api<{
    flattened: Array<Record<string, unknown>>;
    requested: number;
    succeeded: number;
  }>(
    "/api/ops/flatten",
    {
      method: "POST",
      body: JSON.stringify({ reason }),
      headers: buildControlHeaders(options),
    },
    options?.signal,
  );

export const issueWebsocketSession = (options: ControlRequestOptions) =>
  api<{ session: string; expires: number }>(
    "/api/ops/ws-session",
    {
      method: "POST",
      headers: buildControlHeaders(options),
    },
    options?.signal,
  );
