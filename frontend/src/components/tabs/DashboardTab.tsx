import { useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Calendar as CalendarIcon,
  Filter,
  Info,
  RefreshCcw,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, useId } from "react";
import type { DateRange } from "react-day-picker";

import {
  getAlerts,
  getDashboardSummary,
  getHealth,
  getPositions,
  getRecentTrades,
  getStrategies,
  type PageMetadata,
} from "../../lib/api";
import {
  buildSummarySearchParams,
  createDefaultDashboardFilters,
  fromDateRange,
  toDateRange,
} from "../../lib/dashboardFilters";
import { queryKeys } from "../../lib/queryClient";
import { useDashboardFilterActions, useDashboardFilters } from "../../lib/store";
import {
  validateApiResponse,
  dashboardSummarySchema,
  strategyListResponseSchema,
  positionsListResponseSchema,
  tradesListResponseSchema,
  alertsListResponseSchema,
  healthCheckSchema,
} from "../../lib/validation";
import { EquityCurves } from "../charts/EquityCurves";
import { PnlBySymbol } from "../charts/PnlBySymbol";
import { ReturnsHistogram } from "../charts/ReturnsHistogram";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Calendar } from "../ui/calendar";
import { Card } from "../ui/card";
import { Checkbox } from "../ui/checkbox";
import { Label } from "../ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import { ScrollArea } from "../ui/scroll-area";
import { Skeleton } from "../ui/skeleton";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

type EquityPoint = { t: string } & Record<string, number | string>;

const isSameDateRange = (a?: DateRange, b?: DateRange) => {
  if (a?.from?.getTime() !== b?.from?.getTime()) return false;
  if (a?.to?.getTime() !== b?.to?.getTime()) return false;
  return true;
};

const isShallowEqualArray = (a: string[], b: string[]) => {
  if (a.length !== b.length) return false;
  return a.every((value, index) => value === b[index]);
};

const getLastPageInfo = (pages: Array<{ page: PageMetadata | null }> | undefined) => {
  if (!pages?.length) return null;
  const last = pages[pages.length - 1];
  return last?.page ?? null;
};

const PANEL_CLASS =
  "rounded-2xl border border-zinc-800/60 bg-zinc-950/40 backdrop-blur-sm shadow-lg shadow-black/10";

type MetricColor = "emerald" | "red" | "cyan" | "amber" | "zinc";

type MetricItem = {
  key: string;
  label: string;
  value: string | null;
  color: MetricColor;
  subtitle?: string;
  trend?: "up" | "down";
};

export function DashboardTab() {
  const dashboardFilters = useDashboardFilters();
  const { setDashboardFilters } = useDashboardFilterActions();
  const queryClient = useQueryClient();

  const [pendingRange, setPendingRange] = useState<DateRange | undefined>(() =>
    toDateRange(dashboardFilters),
  );
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(
    dashboardFilters.strategies,
  );
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(dashboardFilters.symbols);

  useEffect(() => {
    const nextRange = toDateRange(dashboardFilters);
    setPendingRange((previous) => (isSameDateRange(previous, nextRange) ? previous : nextRange));
    setSelectedStrategies((previous) =>
      isShallowEqualArray(previous, dashboardFilters.strategies)
        ? previous
        : dashboardFilters.strategies,
    );
    setSelectedSymbols((previous) =>
      isShallowEqualArray(previous, dashboardFilters.symbols) ? previous : dashboardFilters.symbols,
    );
  }, [dashboardFilters]);

  const positionsHeadingId = useId();
  const tradesHeadingId = useId();

  const describePage = (page: PageMetadata | null, count: number) => {
    if (!page) return null;
    const segments = [`Showing ${count}`];
    if (typeof page.totalHint === "number") {
      segments.push(`of ${page.totalHint}`);
    }
    if (page.hasMore) {
      segments.push("• more available");
    }
    return segments.join(" ");
  };

  const resetPagedFeeds = useCallback(() => {
    queryClient.removeQueries({ queryKey: queryKeys.dashboard.positions() });
    queryClient.removeQueries({ queryKey: queryKeys.dashboard.trades() });
    queryClient.removeQueries({ queryKey: queryKeys.dashboard.alerts() });
  }, [queryClient]);

  // Build query parameters
  const summaryParams = useMemo(
    () => buildSummarySearchParams(dashboardFilters),
    [dashboardFilters],
  );
  const summaryParamsKey = useMemo(() => summaryParams.toString(), [summaryParams]);

  // React Query hooks for data fetching
  const strategiesQuery = useQuery({
    queryKey: queryKeys.strategies.list(),
    queryFn: () =>
      getStrategies().then((data) => {
        const parsed = validateApiResponse(strategyListResponseSchema, data);
        return parsed.data;
      }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  const summaryQuery = useQuery({
    queryKey: queryKeys.dashboard.summary({ params: summaryParamsKey }),
    queryFn: () =>
      getDashboardSummary(summaryParams).then((data) =>
        validateApiResponse(dashboardSummarySchema, data),
      ),
    staleTime: 30 * 1000, // 30 seconds for real-time data
  });

  const positionsQuery = useInfiniteQuery({
    queryKey: queryKeys.dashboard.positions(),
    queryFn: ({ pageParam }) =>
      getPositions({ cursor: pageParam ?? undefined }).then((data) =>
        validateApiResponse(positionsListResponseSchema, data),
      ),
    getNextPageParam: (lastPage) => lastPage.page.nextCursor ?? undefined,
    staleTime: 10 * 1000,
    initialPageParam: undefined as string | undefined,
  });

  const tradesQuery = useInfiniteQuery({
    queryKey: queryKeys.dashboard.trades(),
    queryFn: ({ pageParam }) =>
      getRecentTrades({ cursor: pageParam ?? undefined }).then((data) =>
        validateApiResponse(tradesListResponseSchema, data),
      ),
    getNextPageParam: (lastPage) => lastPage.page.nextCursor ?? undefined,
    staleTime: 10 * 1000,
    initialPageParam: undefined as string | undefined,
  });

  const alertsQuery = useInfiniteQuery({
    queryKey: queryKeys.dashboard.alerts(),
    queryFn: ({ pageParam }) =>
      getAlerts({ cursor: pageParam ?? undefined }).then((data) =>
        validateApiResponse(alertsListResponseSchema, data),
      ),
    getNextPageParam: (lastPage) => lastPage.page.nextCursor ?? undefined,
    staleTime: 10 * 1000,
    initialPageParam: undefined as string | undefined,
  });

  const positionsPages = positionsQuery.data?.pages ?? [];
  const positions = positionsPages.flatMap((page) => page.data);
  const tradesPages = tradesQuery.data?.pages ?? [];
  const trades = tradesPages.flatMap((page) => page.data);
  const alertsPages = alertsQuery.data?.pages ?? [];
  const alerts = alertsPages.flatMap((page) => page.data);
  const positionsPageInfo = useMemo(() => getLastPageInfo(positionsPages), [positionsPages]);
  const tradesPageInfo = useMemo(() => getLastPageInfo(tradesPages), [tradesPages]);
  const alertsPageInfo = useMemo(() => getLastPageInfo(alertsPages), [alertsPages]);

  const summaryKpis = summaryQuery.data?.kpis;
  const metricItems: MetricItem[] = [
    {
      key: "totalPnl",
      label: "Total PnL",
      value: summaryKpis ? formatCurrency(summaryKpis.totalPnl) : null,
      color: summaryKpis
        ? summaryKpis.totalPnl >= 0
          ? "emerald"
          : "red"
        : ("zinc" as MetricColor),
      trend: summaryKpis ? (summaryKpis.totalPnl >= 0 ? "up" : "down") : undefined,
    },
    {
      key: "winRate",
      label: "Win Rate",
      value: summaryKpis ? formatPercent(summaryKpis.winRate) : null,
      color: "cyan" as MetricColor,
    },
    {
      key: "sharpe",
      label: "Sharpe",
      value: summaryKpis ? summaryKpis.sharpe.toFixed(2) : null,
      color: "amber" as MetricColor,
    },
    {
      key: "drawdown",
      label: "Max Drawdown",
      value: summaryKpis ? formatPercent(summaryKpis.maxDrawdown) : null,
      color: "red" as MetricColor,
    },
    {
      key: "positions",
      label: "Open Positions",
      value: summaryKpis ? summaryKpis.openPositions.toString() : null,
      color: "zinc" as MetricColor,
    },
  ];
  const hasMorePositions =
    Boolean(positionsPageInfo?.nextCursor) ||
    Boolean(positionsPageInfo?.hasMore) ||
    Boolean(positionsQuery.hasNextPage);
  const hasMoreTrades =
    Boolean(tradesPageInfo?.nextCursor) ||
    Boolean(tradesPageInfo?.hasMore) ||
    Boolean(tradesQuery.hasNextPage);
  const hasMoreAlerts =
    Boolean(alertsPageInfo?.nextCursor) ||
    Boolean(alertsPageInfo?.hasMore) ||
    Boolean(alertsQuery.hasNextPage);
  const positionsSummary = describePage(positionsPageInfo, positions.length);
  const tradesSummary = describePage(tradesPageInfo, trades.length);
  const alertsSummary = describePage(alertsPageInfo, alerts.length);

  const loadMorePositions = () => {
    if (!hasMorePositions || positionsQuery.isFetchingNextPage) return;
    void positionsQuery.fetchNextPage();
  };
  const loadMoreTrades = () => {
    if (!hasMoreTrades || tradesQuery.isFetchingNextPage) return;
    void tradesQuery.fetchNextPage();
  };
  const loadMoreAlerts = () => {
    if (!hasMoreAlerts || alertsQuery.isFetchingNextPage) return;
    void alertsQuery.fetchNextPage();
  };

  const healthQuery = useQuery({
    queryKey: queryKeys.dashboard.health(),
    queryFn: () => getHealth().then((data) => validateApiResponse(healthCheckSchema, data)),
    staleTime: 10 * 1000, // 10 seconds
  });

  const symbolOptions = useMemo(() => {
    const symbols = new Set<string>();
    strategiesQuery.data?.forEach((strategy) =>
      strategy.symbols.forEach((symbol) => symbols.add(symbol)),
    );
    summaryQuery.data?.pnlBySymbol.forEach((row) => symbols.add(row.symbol));
    return Array.from(symbols).sort();
  }, [strategiesQuery.data, summaryQuery.data]);

  const equitySeriesKeys = useMemo(() => {
    if (!summaryQuery.data?.equityByStrategy?.length) return [];
    const first = summaryQuery.data.equityByStrategy[0];
    return Object.keys(first)
      .filter((key) => key !== "t")
      .map((key) => ({ key, label: key }));
  }, [summaryQuery.data]);

  const handleApplyFilters = () => {
    const normalizedRange = fromDateRange(pendingRange);
    resetPagedFeeds();
    setDashboardFilters({
      from: normalizedRange.from,
      to: normalizedRange.to,
      strategies: selectedStrategies,
      symbols: selectedSymbols,
    });
  };

  const handleResetFilters = () => {
    const defaults = createDefaultDashboardFilters();
    resetPagedFeeds();
    setDashboardFilters(defaults);
    setPendingRange(toDateRange(defaults));
    setSelectedStrategies([]);
    setSelectedSymbols([]);
  };

  const toggleStrategySelection = (strategyId: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(strategyId)
        ? prev.filter((item) => item !== strategyId)
        : [...prev, strategyId],
    );
  };

  const toggleSymbolSelection = (symbol: string) => {
    setSelectedSymbols((prev) =>
      prev.includes(symbol) ? prev.filter((item) => item !== symbol) : [...prev, symbol],
    );
  };

  const handleRefresh = () => {
    void Promise.all([
      strategiesQuery.refetch(),
      summaryQuery.refetch(),
      positionsQuery.refetch(),
      tradesQuery.refetch(),
      alertsQuery.refetch(),
      healthQuery.refetch(),
    ]);
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-2">
            <Label className="text-xs">Date Range</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex w-48 items-center justify-start gap-2"
                >
                  <CalendarIcon className="h-4 w-4" />
                  {pendingRange?.from && pendingRange?.to
                    ? `${pendingRange.from.toLocaleDateString()} – ${pendingRange.to.toLocaleDateString()}`
                    : "Select range"}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="p-0">
                <Calendar
                  mode="range"
                  selected={pendingRange}
                  onSelect={setPendingRange}
                  numberOfMonths={2}
                  initialFocus
                />
              </PopoverContent>
            </Popover>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Strategies</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex w-56 items-center justify-start gap-2"
                >
                  <Filter className="h-4 w-4" />
                  {selectedStrategies.length > 0
                    ? `${selectedStrategies.length} selected`
                    : "All strategies"}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-64 p-0" align="start">
                <div className="p-3">
                  <ScrollArea className="max-h-64">
                    <div className="space-y-2">
                      {strategiesQuery.data?.map((strategy) => (
                        <label key={strategy.id} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={selectedStrategies.includes(strategy.id)}
                            onCheckedChange={() => toggleStrategySelection(strategy.id)}
                          />
                          <span>{strategy.name}</span>
                        </label>
                      ))}
                      {strategiesQuery.data?.length === 0 && (
                        <p className="text-xs text-muted-foreground">No strategies available</p>
                      )}
                    </div>
                  </ScrollArea>
                </div>
              </PopoverContent>
            </Popover>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Symbols</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex w-56 items-center justify-start gap-2"
                >
                  <Filter className="h-4 w-4" />
                  {selectedSymbols.length > 0
                    ? `${selectedSymbols.length} selected`
                    : "All symbols"}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-64 p-0" align="start">
                <div className="p-3">
                  <ScrollArea className="max-h-64">
                    <div className="space-y-2">
                      {symbolOptions.map((symbol) => (
                        <label key={symbol} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={selectedSymbols.includes(symbol)}
                            onCheckedChange={() => toggleSymbolSelection(symbol)}
                          />
                          <span>{symbol}</span>
                        </label>
                      ))}
                      {symbolOptions.length === 0 && (
                        <p className="text-xs text-muted-foreground">No symbols available</p>
                      )}
                    </div>
                  </ScrollArea>
                </div>
              </PopoverContent>
            </Popover>
          </div>

          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={handleApplyFilters}
              disabled={strategiesQuery.isLoading || summaryQuery.isLoading}
            >
              Apply Filters
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleResetFilters}
              disabled={strategiesQuery.isLoading || summaryQuery.isLoading}
            >
              Reset
            </Button>
            <Button
              size="icon"
              variant="outline"
              onClick={handleRefresh}
              disabled={strategiesQuery.isLoading || summaryQuery.isLoading}
            >
              <RefreshCcw
                className={`h-4 w-4 ${strategiesQuery.isLoading || summaryQuery.isLoading ? "animate-spin" : ""}`}
              />
            </Button>
          </div>
        </div>

        {(selectedStrategies.length > 0 || selectedSymbols.length > 0) && (
          <div className="mt-4 flex flex-wrap gap-2">
            {selectedStrategies.map((strategyId) => {
              const strategy = strategiesQuery.data?.find((item) => item.id === strategyId);
              return (
                <Badge key={strategyId} variant="outline">
                  {strategy?.name ?? strategyId}
                </Badge>
              );
            })}
            {selectedSymbols.map((symbol) => (
              <Badge key={symbol} variant="secondary">
                {symbol}
              </Badge>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
        {metricItems.map((item) => (
          <MetricCard
            key={item.key}
            label={item.label}
            value={item.value}
            color={item.color}
            subtitle={item.subtitle}
            trend={item.trend}
            loading={!summaryKpis}
          />
        ))}
      </div>

      <Card className={`${PANEL_CLASS} space-y-4 p-5`}>
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Equity Curves</h3>
        </div>
        <EquityCurves
          data={(summaryQuery.data?.equityByStrategy ?? []) as EquityPoint[]}
          series={equitySeriesKeys}
        />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className={`${PANEL_CLASS} space-y-4 p-5 min-h-[360px]`}>
          <h3 className="font-medium">PnL by Symbol</h3>
          <PnlBySymbol data={summaryQuery.data?.pnlBySymbol ?? []} />
        </Card>
        <Card className={`${PANEL_CLASS} space-y-4 p-5 min-h-[360px]`}>
          <h3 className="font-medium">Distribution of Returns</h3>
          <ReturnsHistogram returns={summaryQuery.data?.returns ?? []} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card className={`${PANEL_CLASS} flex flex-col p-5 min-h-[360px]`}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 id={positionsHeadingId} className="font-medium">
              Open Positions
            </h3>
            {positionsSummary ? (
              <span className="text-xs text-muted-foreground text-right">{positionsSummary}</span>
            ) : null}
          </div>
          <div className="mt-2 flex-1 overflow-auto rounded-xl border border-zinc-900/40">
            <Table aria-labelledby={positionsHeadingId}>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Qty</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>Mark</TableHead>
                  <TableHead className="text-right">PnL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((position) => (
                  <TableRow key={position.id}>
                    <TableCell>{position.symbol}</TableCell>
                    <TableCell>{position.qty}</TableCell>
                    <TableCell>{formatCurrency(position.entry)}</TableCell>
                    <TableCell>{formatCurrency(position.mark)}</TableCell>
                    <TableCell
                      className={`text-right ${position.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {formatCurrency(position.pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableCaption>
                {positions.length === 0 ? "No open positions" : undefined}
              </TableCaption>
            </Table>
          </div>
          {hasMorePositions ? (
            <div className="mt-3 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={loadMorePositions}
                disabled={positionsQuery.isFetchingNextPage || !hasMorePositions}
              >
                {positionsQuery.isFetchingNextPage ? "Loading…" : "Load older positions"}
              </Button>
            </div>
          ) : null}
        </Card>

        <Card className={`${PANEL_CLASS} flex flex-col p-5 min-h-[360px]`}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 id={tradesHeadingId} className="font-medium">
              Recent Trades
            </h3>
            {tradesSummary ? (
              <span className="text-xs text-muted-foreground text-right">{tradesSummary}</span>
            ) : null}
          </div>
          <div className="mt-2 flex-1 overflow-auto rounded-xl border border-zinc-900/40">
            <Table aria-labelledby={tradesHeadingId}>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead>Qty</TableHead>
                  <TableHead>Price</TableHead>
                  <TableHead className="text-right">PnL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade) => (
                  <TableRow key={trade.id}>
                    <TableCell>{new Date(trade.timestamp).toLocaleTimeString()}</TableCell>
                    <TableCell>{trade.symbol}</TableCell>
                    <TableCell
                      className={trade.side === "buy" ? "text-emerald-400" : "text-red-400"}
                    >
                      {trade.side.toUpperCase()}
                    </TableCell>
                    <TableCell>{trade.quantity}</TableCell>
                    <TableCell>{formatCurrency(trade.price)}</TableCell>
                    <TableCell className="text-right">
                      {trade.pnl !== undefined ? formatCurrency(trade.pnl) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableCaption>{trades.length === 0 ? "No recent trades" : undefined}</TableCaption>
            </Table>
          </div>
          {hasMoreTrades ? (
            <div className="mt-3 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={loadMoreTrades}
                disabled={tradesQuery.isFetchingNextPage || !hasMoreTrades}
              >
                {tradesQuery.isFetchingNextPage ? "Loading…" : "Load older trades"}
              </Button>
            </div>
          ) : null}
        </Card>

        <Card className={`${PANEL_CLASS} flex flex-col p-5 min-h-[360px]`}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="font-medium">Alerts</h3>
            {alertsSummary ? (
              <span className="text-xs text-muted-foreground text-right">{alertsSummary}</span>
            ) : null}
          </div>
          <ScrollArea className="mt-2 flex-1 pr-2">
            <div className="space-y-3">
              {alerts.map((alert) => {
                const visuals = getAlertVisuals(alert.type);
                return (
                  <div
                    key={alert.id}
                    className={`flex items-start gap-3 rounded-xl border p-3 ${visuals.bg} ${visuals.border}`}
                  >
                    <div className={`rounded-full p-1 ${visuals.color}`}>{visuals.icon}</div>
                    <div className="flex-1">
                      <p className="text-sm text-zinc-200">{alert.message}</p>
                      <p className="text-xs text-zinc-500">
                        {new Date(alert.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                );
              })}
              {alerts.length === 0 && <p className="text-xs text-muted-foreground">No alerts</p>}
            </div>
          </ScrollArea>
          {hasMoreAlerts ? (
            <div className="mt-3 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={loadMoreAlerts}
                disabled={alertsQuery.isFetchingNextPage || !hasMoreAlerts}
              >
                {alertsQuery.isFetchingNextPage ? "Loading…" : "Load older alerts"}
              </Button>
            </div>
          ) : null}
        </Card>

        <Card className={`${PANEL_CLASS} flex flex-col p-5 min-h-[360px]`}>
          <h3 className="mb-3 font-medium">Venue Health</h3>
          <div className="space-y-3">
            {healthQuery.data?.venues.map((venue) => (
              <div key={venue.name} className="rounded-xl border border-zinc-900/40 p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{venue.name}</span>
                  <Badge
                    variant={
                      venue.status === "ok"
                        ? "outline"
                        : venue.status === "warn"
                          ? "secondary"
                          : "destructive"
                    }
                  >
                    {venue.status.toUpperCase()}
                  </Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <span>Latency: {venue.latencyMs.toFixed(1)} ms</span>
                  <span>Queue: {venue.queue}</span>
                </div>
              </div>
            ))}
            {!healthQuery.data?.venues?.length && (
              <p className="text-xs text-muted-foreground">No venue data</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string | null;
  subtitle?: string;
  trend?: "up" | "down";
  color: MetricColor;
  loading: boolean;
}

function MetricCard({ label, value, subtitle, trend, color, loading }: MetricCardProps) {
  const colorClasses: Record<MetricColor, string> = {
    emerald: "text-emerald-400",
    red: "text-red-400",
    cyan: "text-cyan-300",
    amber: "text-amber-300",
    zinc: "text-zinc-200",
  };

  return (
    <div className={`${PANEL_CLASS} min-h-[130px] space-y-2 p-5`}>
      <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-zinc-500">
        <span>{label}</span>
        {trend === "up" ? (
          <TrendingUp className="h-4 w-4 text-emerald-400" />
        ) : trend === "down" ? (
          <TrendingDown className="h-4 w-4 text-red-400" />
        ) : null}
      </div>
      <div className={`font-mono text-2xl ${colorClasses[color]}`}>
        {loading ? <Skeleton className="h-6 w-24" /> : (value ?? "—")}
      </div>
      {subtitle ? <p className="text-xs text-zinc-500">{subtitle}</p> : null}
    </div>
  );
}

function getAlertVisuals(type: string) {
  if (type === "error") {
    return {
      icon: <AlertCircle className="h-4 w-4" />,
      color: "bg-red-500/10 text-red-400",
      bg: "bg-red-500/5",
      border: "border-red-400/30",
    };
  }
  if (type === "warning") {
    return {
      icon: <AlertTriangle className="h-4 w-4" />,
      color: "bg-amber-500/10 text-amber-300",
      bg: "bg-amber-500/5",
      border: "border-amber-300/30",
    };
  }
  return {
    icon: <Info className="h-4 w-4" />,
    color: "bg-cyan-500/10 text-cyan-300",
    bg: "bg-cyan-500/5",
    border: "border-cyan-300/30",
  };
}
