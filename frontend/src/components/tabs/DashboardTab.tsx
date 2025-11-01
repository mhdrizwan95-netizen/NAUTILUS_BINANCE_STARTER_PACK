import { useMemo, useState } from 'react';
import { DateRange } from 'react-day-picker';
import { Calendar as CalendarIcon, Filter, RefreshCcw } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Calendar } from '../ui/calendar';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { Badge } from '../ui/badge';
import { Label } from '../ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover';
import { Checkbox } from '../ui/checkbox';
import { Separator } from '../ui/separator';
import { ScrollArea } from '../ui/scroll-area';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { Skeleton } from '../ui/skeleton';
import { EquityCurves } from '../charts/EquityCurves';
import { PnlBySymbol } from '../charts/PnlBySymbol';
import { ReturnsHistogram } from '../charts/ReturnsHistogram';
import {
  getAlerts,
  getDashboardSummary,
  getHealth,
  getPositions,
  getRecentTrades,
  getStrategies,
} from '../../lib/api';
import { queryKeys } from '../../lib/queryClient';
import { validateApiResponse } from '../../lib/validation';
import {
  dashboardSummarySchema,
  strategySummarySchema,
  positionSchema,
  tradeSchema,
  alertSchema,
  healthCheckSchema
} from '../../lib/validation';
import type { StrategySummary } from '../../types/trading';

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

const getDefaultRange = (): DateRange => {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 7);
  return { from, to };
};

export function DashboardTab() {
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [appliedStrategies, setAppliedStrategies] = useState<string[]>([]);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const [appliedSymbols, setAppliedSymbols] = useState<string[]>([]);
  const [pendingRange, setPendingRange] = useState<DateRange | undefined>(() => getDefaultRange());
  const [activeRange, setActiveRange] = useState<DateRange | undefined>(() => getDefaultRange());

  // Build query parameters
  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    if (activeRange?.from) params.set('from', activeRange.from.toISOString());
    if (activeRange?.to) params.set('to', activeRange.to.toISOString());
    appliedStrategies.forEach((strategyId) => params.append('strategies[]', strategyId));
    appliedSymbols.forEach((symbol) => params.append('symbols[]', symbol));
    return params;
  }, [activeRange, appliedStrategies, appliedSymbols]);

  // React Query hooks for data fetching
  const strategiesQuery = useQuery({
    queryKey: queryKeys.strategies.list(),
    queryFn: () => getStrategies().then(data => validateApiResponse(strategySummarySchema.array(), data)),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  const summaryQuery = useQuery({
    queryKey: queryKeys.dashboard.summary(Object.fromEntries(queryParams.entries())),
    queryFn: () => getDashboardSummary(queryParams).then(data => validateApiResponse(dashboardSummarySchema, data)),
    staleTime: 30 * 1000, // 30 seconds for real-time data
  });

  const positionsQuery = useQuery({
    queryKey: queryKeys.dashboard.positions(),
    queryFn: () => getPositions().then(data => validateApiResponse(positionSchema.array(), data)),
    staleTime: 10 * 1000, // 10 seconds
  });

  const tradesQuery = useQuery({
    queryKey: queryKeys.dashboard.trades(),
    queryFn: () => getRecentTrades().then(data => validateApiResponse(tradeSchema.array(), data)),
    staleTime: 10 * 1000, // 10 seconds
  });

  const alertsQuery = useQuery({
    queryKey: queryKeys.dashboard.alerts(),
    queryFn: () => getAlerts().then(data => validateApiResponse(alertSchema.array(), data)),
    staleTime: 10 * 1000, // 10 seconds
  });

  const healthQuery = useQuery({
    queryKey: queryKeys.dashboard.health(),
    queryFn: () => getHealth().then(data => validateApiResponse(healthCheckSchema, data)),
    staleTime: 10 * 1000, // 10 seconds
  });

  const symbolOptions = useMemo(() => {
    const symbols = new Set<string>();
    strategiesQuery.data?.forEach((strategy) => strategy.symbols.forEach((symbol) => symbols.add(symbol)));
    summaryQuery.data?.pnlBySymbol.forEach((row) => symbols.add(row.symbol));
    return Array.from(symbols).sort();
  }, [strategiesQuery.data, summaryQuery.data]);

  const equitySeriesKeys = useMemo(() => {
    if (!summaryQuery.data?.equityByStrategy?.length) return [];
    const first = summaryQuery.data.equityByStrategy[0];
    return Object.keys(first)
      .filter((key) => key !== 't')
      .map((key) => ({ key, label: key }));
  }, [summaryQuery.data]);

  const handleApplyFilters = () => {
    setActiveRange(pendingRange);
    setAppliedStrategies(selectedStrategies);
    setAppliedSymbols(selectedSymbols);
  };

  const handleResetFilters = () => {
    const resetRange = getDefaultRange();
    setPendingRange(resetRange);
    setActiveRange(resetRange);
    setSelectedStrategies([]);
    setAppliedStrategies([]);
    setSelectedSymbols([]);
    setAppliedSymbols([]);
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
    // Invalidate and refetch all queries
    strategiesQuery.refetch();
    summaryQuery.refetch();
    positionsQuery.refetch();
    tradesQuery.refetch();
    alertsQuery.refetch();
    healthQuery.refetch();
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-2">
            <Label className="text-xs">Date Range</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="flex w-48 items-center justify-start gap-2">
                  <CalendarIcon className="h-4 w-4" />
                  {pendingRange?.from && pendingRange?.to
                    ? `${pendingRange.from.toLocaleDateString()} – ${pendingRange.to.toLocaleDateString()}`
                    : 'Select range'}
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
                <Button variant="outline" size="sm" className="flex w-56 items-center justify-start gap-2">
                  <Filter className="h-4 w-4" />
                  {selectedStrategies.length > 0
                    ? `${selectedStrategies.length} selected`
                    : 'All strategies'}
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
                <Button variant="outline" size="sm" className="flex w-56 items-center justify-start gap-2">
                  <Filter className="h-4 w-4" />
                  {selectedSymbols.length > 0
                    ? `${selectedSymbols.length} selected`
                    : 'All symbols'}
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
            <Button size="sm" onClick={handleApplyFilters} disabled={strategiesQuery.isLoading || summaryQuery.isLoading}>
              Apply Filters
            </Button>
            <Button size="sm" variant="ghost" onClick={handleResetFilters} disabled={strategiesQuery.isLoading || summaryQuery.isLoading}>
              Reset
            </Button>
            <Button size="icon" variant="outline" onClick={handleRefresh} disabled={strategiesQuery.isLoading || summaryQuery.isLoading}>
              <RefreshCcw className={`h-4 w-4 ${strategiesQuery.isLoading || summaryQuery.isLoading ? 'animate-spin' : ''}`} />
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
            {summaryQuery.data ? formatCurrency(summaryQuery.data.kpis.totalPnl) : <Skeleton className="h-6 w-32" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Win Rate</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? formatPercent(summaryQuery.data.kpis.winRate) : <Skeleton className="h-6 w-24" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Sharpe</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? summaryQuery.data.kpis.sharpe.toFixed(2) : <Skeleton className="h-6 w-16" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Max Drawdown</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? formatPercent(summaryQuery.data.kpis.maxDrawdown) : <Skeleton className="h-6 w-24" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Open Positions</div>
          <div className="text-lg font-semibold">
            {summaryQuery.data ? summaryQuery.data.kpis.openPositions : <Skeleton className="h-6 w-12" />}
          </div>
        </Card>
      </div>

      <Card className="space-y-4 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Equity Curves</h3>
        </div>
        <EquityCurves data={summaryQuery.data?.equityByStrategy as any ?? []} series={equitySeriesKeys} />
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
          <h3 className="mb-3 font-medium">Open Positions</h3>
          <Table>
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
              {positionsQuery.data?.map((position) => (
                <TableRow key={position.symbol}>
                  <TableCell>{position.symbol}</TableCell>
                  <TableCell>{position.qty}</TableCell>
                  <TableCell>{formatCurrency(position.entry)}</TableCell>
                  <TableCell>{formatCurrency(position.mark)}</TableCell>
                  <TableCell className={`text-right ${position.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatCurrency(position.pnl)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableCaption>{positionsQuery.data?.length === 0 ? 'No open positions' : undefined}</TableCaption>
          </Table>
        </Card>

        <Card className="p-4">
          <h3 className="mb-3 font-medium">Recent Trades</h3>
          <Table>
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
              {tradesQuery.data?.map((trade) => (
                <TableRow key={`${trade.timestamp}-${trade.symbol}-${trade.side}`}>
                  <TableCell>{new Date(trade.timestamp).toLocaleTimeString()}</TableCell>
                  <TableCell>{trade.symbol}</TableCell>
                  <TableCell className={trade.side === 'buy' ? 'text-emerald-400' : 'text-red-400'}>
                    {trade.side.toUpperCase()}
                  </TableCell>
                  <TableCell>{trade.quantity}</TableCell>
                  <TableCell>{formatCurrency(trade.price)}</TableCell>
                  <TableCell className="text-right">
                    {trade.pnl !== undefined ? formatCurrency(trade.pnl) : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableCaption>{tradesQuery.data?.length === 0 ? 'No recent trades' : undefined}</TableCaption>
          </Table>
        </Card>

        <Card className="p-4">
          <h3 className="mb-3 font-medium">Alerts</h3>
          <ScrollArea className="h-64 pr-2">
            <div className="space-y-3">
              {alertsQuery.data?.map((alert) => (
                <div key={`${alert.timestamp}-${alert.message}`} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{new Date(alert.timestamp).toLocaleTimeString()}</span>
                    <Badge
                      variant={
                        alert.type === 'error'
                          ? 'destructive'
                          : alert.type === 'warning'
                          ? 'secondary'
                          : 'outline'
                      }
                    >
                      {alert.type.toUpperCase()}
                    </Badge>
                  </div>
                  <Separator className="my-2" />
                  <p className="text-sm leading-tight text-muted-foreground">{alert.message}</p>
                </div>
              ))}
              {alertsQuery.data?.length === 0 && <p className="text-xs text-muted-foreground">No alerts</p>}
            </div>
          </ScrollArea>
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
                      venue.status === 'ok'
                        ? 'outline'
                        : venue.status === 'warn'
                        ? 'secondary'
                        : 'destructive'
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
            {!healthQuery.data?.venues?.length && <p className="text-xs text-muted-foreground">No venue data</p>}
          </div>
        </Card>
      </div>
    </div>
  );
}
