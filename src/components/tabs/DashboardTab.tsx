import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DateRange } from 'react-day-picker';
import { Calendar as CalendarIcon, Filter, RefreshCcw } from 'lucide-react';
import { toast } from 'sonner';
import { Calendar } from '@/components/ui/calendar';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { EquityCurves } from '@/components/charts/EquityCurves';
import { PnlBySymbol } from '@/components/charts/PnlBySymbol';
import { ReturnsHistogram } from '@/components/charts/ReturnsHistogram';
import {
  getAlerts,
  getDashboardSummary,
  getHealth,
  getPositions,
  getRecentTrades,
  getStrategies,
} from '@/lib/api';
import type { StrategySummary } from '@/types/trading';

type DashboardSummary = Awaited<ReturnType<typeof getDashboardSummary>>;
type PositionsResponse = Awaited<ReturnType<typeof getPositions>>;
type TradesResponse = Awaited<ReturnType<typeof getRecentTrades>>;
type AlertsResponse = Awaited<ReturnType<typeof getAlerts>>;
type HealthResponse = Awaited<ReturnType<typeof getHealth>>;

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
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [positions, setPositions] = useState<PositionsResponse>([]);
  const [trades, setTrades] = useState<TradesResponse>([]);
  const [alerts, setAlertsData] = useState<AlertsResponse>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [appliedStrategies, setAppliedStrategies] = useState<string[]>([]);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const [appliedSymbols, setAppliedSymbols] = useState<string[]>([]);
  const [pendingRange, setPendingRange] = useState<DateRange | undefined>(() => getDefaultRange());
  const [activeRange, setActiveRange] = useState<DateRange | undefined>(() => getDefaultRange());

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getStrategies(controller.signal)
      .then(setStrategies)
      .catch((error) => {
        if (!controller.signal.aborted) {
          console.warn('Failed to load strategies', error);
        }
      });
    return () => controller.abort();
  }, []);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);

    const params = new URLSearchParams();
    if (activeRange?.from) params.set('from', activeRange.from.toISOString());
    if (activeRange?.to) params.set('to', activeRange.to.toISOString());
    appliedStrategies.forEach((strategyId) => params.append('strategies[]', strategyId));
    appliedSymbols.forEach((symbol) => params.append('symbols[]', symbol));

    try {
      const [summaryPayload, positionsPayload, tradesPayload, alertsPayload, healthPayload] =
        await Promise.all([
          getDashboardSummary(params, controller.signal),
          getPositions(controller.signal),
          getRecentTrades(controller.signal),
          getAlerts(controller.signal),
          getHealth(controller.signal),
        ]);

      if (!controller.signal.aborted) {
        setSummary(summaryPayload);
        setPositions(positionsPayload);
        setTrades(tradesPayload);
        setAlertsData(alertsPayload);
        setHealth(healthPayload);
      }
    } catch (error) {
      if (!controller.signal.aborted && error instanceof Error) {
        toast.error('Failed to refresh dashboard', { description: error.message });
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [activeRange, appliedStrategies, appliedSymbols]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const symbolOptions = useMemo(() => {
    const symbols = new Set<string>();
    strategies.forEach((strategy) => strategy.symbols.forEach((symbol) => symbols.add(symbol)));
    summary?.pnlBySymbol.forEach((row) => symbols.add(row.symbol));
    return Array.from(symbols).sort();
  }, [strategies, summary]);

  const equitySeriesKeys = useMemo(() => {
    if (!summary?.equityByStrategy?.length) return [];
    const first = summary.equityByStrategy[0];
    return Object.keys(first)
      .filter((key) => key !== 't')
      .map((key) => ({ key, label: key }));
  }, [summary]);

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

  return (
    <div className="space-y-6 p-6">
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
                      {strategies.map((strategy) => (
                        <label key={strategy.id} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={selectedStrategies.includes(strategy.id)}
                            onCheckedChange={() => toggleStrategySelection(strategy.id)}
                          />
                          <span>{strategy.name}</span>
                        </label>
                      ))}
                      {strategies.length === 0 && (
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
            <Button size="sm" onClick={handleApplyFilters} disabled={loading}>
              Apply Filters
            </Button>
            <Button size="sm" variant="ghost" onClick={handleResetFilters} disabled={loading}>
              Reset
            </Button>
            <Button size="icon" variant="outline" onClick={() => load()} disabled={loading}>
              <RefreshCcw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>

        {(selectedStrategies.length > 0 || selectedSymbols.length > 0) && (
          <div className="mt-4 flex flex-wrap gap-2">
            {selectedStrategies.map((strategyId) => {
              const strategy = strategies.find((item) => item.id === strategyId);
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
            {summary ? formatCurrency(summary.kpis.totalPnl) : <Skeleton className="h-6 w-32" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Win Rate</div>
          <div className="text-lg font-semibold">
            {summary ? formatPercent(summary.kpis.winRate) : <Skeleton className="h-6 w-24" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Sharpe</div>
          <div className="text-lg font-semibold">
            {summary ? summary.kpis.sharpe.toFixed(2) : <Skeleton className="h-6 w-16" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Max Drawdown</div>
          <div className="text-lg font-semibold">
            {summary ? formatPercent(summary.kpis.maxDrawdown) : <Skeleton className="h-6 w-24" />}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-muted-foreground">Open Positions</div>
          <div className="text-lg font-semibold">
            {summary ? summary.kpis.openPositions : <Skeleton className="h-6 w-12" />}
          </div>
        </Card>
      </div>

      <Card className="space-y-4 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Equity Curves</h3>
        </div>
        <EquityCurves data={summary?.equityByStrategy ?? []} series={equitySeriesKeys} />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="space-y-4 p-4">
          <h3 className="font-medium">PnL by Symbol</h3>
          <PnlBySymbol data={summary?.pnlBySymbol ?? []} />
        </Card>
        <Card className="space-y-4 p-4">
          <h3 className="font-medium">Distribution of Returns</h3>
          <ReturnsHistogram returns={summary?.returns ?? []} />
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
              {positions.map((position) => (
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
            <TableCaption>{positions.length === 0 ? 'No open positions' : undefined}</TableCaption>
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
              {trades.map((trade) => (
                <TableRow key={`${trade.time}-${trade.symbol}-${trade.side}`}>
                  <TableCell>{new Date(trade.time).toLocaleTimeString()}</TableCell>
                  <TableCell>{trade.symbol}</TableCell>
                  <TableCell className={trade.side === 'buy' ? 'text-emerald-400' : 'text-red-400'}>
                    {trade.side.toUpperCase()}
                  </TableCell>
                  <TableCell>{trade.qty}</TableCell>
                  <TableCell>{formatCurrency(trade.price)}</TableCell>
                  <TableCell className="text-right">
                    {trade.pnl !== undefined ? formatCurrency(trade.pnl) : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableCaption>{trades.length === 0 ? 'No recent trades' : undefined}</TableCaption>
          </Table>
        </Card>

        <Card className="p-4">
          <h3 className="mb-3 font-medium">Alerts</h3>
          <ScrollArea className="h-64 pr-2">
            <div className="space-y-3">
              {alerts.map((alert) => (
                <div key={`${alert.time}-${alert.text}`} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{new Date(alert.time).toLocaleTimeString()}</span>
                    <Badge
                      variant={
                        alert.level === 'error'
                          ? 'destructive'
                          : alert.level === 'warn'
                          ? 'secondary'
                          : 'outline'
                      }
                    >
                      {alert.level.toUpperCase()}
                    </Badge>
                  </div>
                  <Separator className="my-2" />
                  <p className="text-sm leading-tight text-muted-foreground">{alert.text}</p>
                </div>
              ))}
              {alerts.length === 0 && <p className="text-xs text-muted-foreground">No alerts</p>}
            </div>
          </ScrollArea>
        </Card>

        <Card className="p-4">
          <h3 className="mb-3 font-medium">Venue Health</h3>
          <div className="space-y-3">
            {health?.venues.map((venue) => (
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
            {!health?.venues?.length && <p className="text-xs text-muted-foreground">No venue data</p>}
          </div>
        </Card>
      </div>
    </div>
  );
}
