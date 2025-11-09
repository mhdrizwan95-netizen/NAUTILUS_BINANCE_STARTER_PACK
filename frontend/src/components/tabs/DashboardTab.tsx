import { useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar as CalendarIcon, Filter, RefreshCcw } from "lucide-react";
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
import {
  useDashboardFilterActions,
  useDashboardFilters,
  usePagination,
  usePaginationActions,
} from "../../lib/store";
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
import { Separator } from "../ui/separator";
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

export function DashboardTab() {
  const dashboardFilters = useDashboardFilters();
  const { setDashboardFilters } = useDashboardFilterActions();
  const { setPagination, clearPagination } = usePaginationActions();
  const positionsPageInfo = usePagination("positions");
  const tradesPageInfo = usePagination("trades");
  const alertsPageInfo = usePagination("alerts");
  const queryClient = useQueryClient();

  const [pendingRange, setPendingRange] = useState<DateRange | undefined>(() =>
    toDateRange(dashboardFilters),
  );
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(
    dashboardFilters.strategies,
  );
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(dashboardFilters.symbols);

  useEffect(() => {
    setPendingRange(toDateRange(dashboardFilters));
    setSelectedStrategies(dashboardFilters.strategies);
    setSelectedSymbols(dashboardFilters.symbols);
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
    clearPagination("positions", "trades", "alerts");
    queryClient.removeQueries({ queryKey: queryKeys.dashboard.positions() });
    queryClient.removeQueries({ queryKey: queryKeys.dashboard.trades() });
    queryClient.removeQueries({ queryKey: queryKeys.dashboard.alerts() });
  }, [clearPagination, queryClient]);

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

  useEffect(() => {
    const pages = positionsQuery.data?.pages;
    if (!pages?.length) return;
    const last = pages[pages.length - 1];
    if (last?.page) {
      setPagination("positions", last.page);
    }
  }, [positionsQuery.data, setPagination]);

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

  useEffect(() => {
    const pages = tradesQuery.data?.pages;
    if (!pages?.length) return;
    const last = pages[pages.length - 1];
    if (last?.page) {
      setPagination("trades", last.page);
    }
  }, [setPagination, tradesQuery.data]);

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

  useEffect(() => {
    const pages = alertsQuery.data?.pages;
    if (!pages?.length) return;
    const last = pages[pages.length - 1];
    if (last?.page) {
      setPagination("alerts", last.page);
    }
  }, [alertsQuery.data, setPagination]);

  const positionsPages = positionsQuery.data?.pages ?? [];
  const positions = positionsPages.flatMap((page) => page.data);
  const tradesPages = tradesQuery.data?.pages ?? [];
  const trades = tradesPages.flatMap((page) => page.data);
  const alertsPages = alertsQuery.data?.pages ?? [];
  const alerts = alertsPages.flatMap((page) => page.data);
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Total PnL</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? (
              formatCurrency(summaryQuery.data.kpis.totalPnl)
            ) : (
              <Skeleton className="h-6 w-32" />
            )}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Win Rate</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? (
              formatPercent(summaryQuery.data.kpis.winRate)
            ) : (
              <Skeleton className="h-6 w-24" />
            )}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Sharpe</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? (
              summaryQuery.data.kpis.sharpe.toFixed(2)
            ) : (
              <Skeleton className="h-6 w-16" />
            )}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Max Drawdown</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? (
              formatPercent(summaryQuery.data.kpis.maxDrawdown)
            ) : (
              <Skeleton className="h-6 w-24" />
            )}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Positions</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? (
              summaryQuery.data.kpis.openPositions
            ) : (
              <Skeleton className="h-6 w-12" />
            )}
          </div>
        </Card>
      </div>

      <Card className="space-y-4 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Equity Curves</h3>
        </div>
        <EquityCurves
          data={(summaryQuery.data?.equityByStrategy ?? []) as EquityPoint[]}
          series={equitySeriesKeys}
        />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="space-y-4 p-4">
          <h3 className="font-medium">PnL by Symbol</h3>
          <PnlBySymbol data={summaryQuery.data?.pnlBySymbol ?? []} />
        </Card>
        <Card className="space-y-4 p-4">
          <h3 className="font-medium">Distribution of Returns</h3>
          <ReturnsHistogram returns={summaryQuery.data?.returns ?? []} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 id={positionsHeadingId} className="font-medium">
              Open Positions
            </h3>
            {positionsSummary ? (
              <span className="text-xs text-muted-foreground text-right">{positionsSummary}</span>
            ) : null}
          </div>
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
            <TableCaption>{positions.length === 0 ? "No open positions" : undefined}</TableCaption>
          </Table>
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

        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 id={tradesHeadingId} className="font-medium">
              Recent Trades
            </h3>
            {tradesSummary ? (
              <span className="text-xs text-muted-foreground text-right">{tradesSummary}</span>
            ) : null}
          </div>
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
                  <TableCell className={trade.side === "buy" ? "text-emerald-400" : "text-red-400"}>
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

        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="font-medium">Alerts</h3>
            {alertsSummary ? (
              <span className="text-xs text-muted-foreground text-right">{alertsSummary}</span>
            ) : null}
          </div>
          <ScrollArea className="h-64 pr-2">
            <div className="space-y-3">
              {alerts.map((alert) => (
                <div key={alert.id} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{new Date(alert.timestamp).toLocaleTimeString()}</span>
                    <Badge
                      variant={
                        alert.type === "error"
                          ? "destructive"
                          : alert.type === "warning"
                            ? "secondary"
                            : "outline"
                      }
                    >
                      {alert.type.toUpperCase()}
                    </Badge>
                  </div>
                  <Separator className="my-2" />
                  <p className="text-sm leading-tight text-muted-foreground">{alert.message}</p>
                </div>
              ))}
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

        <Card className="p-4">
          <h3 className="mb-3 font-medium">Venue Health</h3>
          <div className="space-y-3">
            {healthQuery.data?.venues.map((venue) => (
              <div key={venue.name} className="rounded-md border border-border p-3 text-sm">
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
