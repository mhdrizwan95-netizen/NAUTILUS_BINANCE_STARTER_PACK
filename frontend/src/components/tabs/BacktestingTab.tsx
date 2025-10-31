import { useCallback, useEffect, useMemo, useState } from 'react';
import { DateRange } from 'react-day-picker';
import {
  Calendar as CalendarIcon,
  Filter,
  Play,
  RotateCcw,
  Download,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Checkbox } from '@/components/ui/checkbox';
import { Calendar } from '@/components/ui/calendar';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { DynamicParamForm } from '@/components/forms/DynamicParamForm';
import { EquityCurves } from '@/components/charts/EquityCurves';
import { PnlBySymbol } from '@/components/charts/PnlBySymbol';
import { ReturnsHistogram } from '@/components/charts/ReturnsHistogram';
import { usePolling } from '@/lib/hooks';
import {
  getStrategies,
  pollBacktest,
  startBacktest,
} from '@/lib/api';
import type { StrategySummary } from '@/types/trading';

type BacktestPoll = Awaited<ReturnType<typeof pollBacktest>>;

const getDefaultRange = (): DateRange => {
  const to = new Date();
  const from = new Date();
  from.setMonth(from.getMonth() - 1);
  return { from, to };
};

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

export function BacktestingTab() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>('');
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const [dateRange, setDateRange] = useState<DateRange | undefined>(() => getDefaultRange());
  const [initialCapital, setInitialCapital] = useState(10000);
  const [feeBps, setFeeBps] = useState(5);
  const [slippageBps, setSlippageBps] = useState(2);
  const [overrides, setOverrides] = useState<Record<string, unknown>>({});
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobSnapshot, setJobSnapshot] = useState<BacktestPoll | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const selectedStrategy = useMemo(
    () => strategies.find((strategy) => strategy.id === selectedStrategyId) ?? null,
    [strategies, selectedStrategyId],
  );

  useEffect(() => {
    const controller = new AbortController();
    getStrategies(controller.signal)
      .then((payload) => {
        setStrategies(payload);
        if (!selectedStrategyId && payload.length) {
          setSelectedStrategyId(payload[0].id);
          setSelectedSymbols(payload[0].symbols);
          setOverrides(payload[0].params ?? {});
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && error instanceof Error) {
          toast.error('Unable to load strategies', { description: error.message });
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (selectedStrategy) {
      setSelectedSymbols(selectedStrategy.symbols);
      setOverrides(selectedStrategy.params ?? {});
    }
  }, [selectedStrategy]);

  const pollingFn = useCallback(() => {
    if (!jobId) return Promise.resolve(null as BacktestPoll | null);
    return pollBacktest(jobId);
  }, [jobId]);

  const { data: polledJob } = usePolling<BacktestPoll | null>(pollingFn, 1200, Boolean(jobId));

  useEffect(() => {
    if (polledJob) {
      setJobSnapshot(polledJob);
      if (polledJob.status === 'done') {
        toast.success('Backtest completed', { description: 'Results ready below' });
        setJobId(null);
      } else if (polledJob.status === 'error') {
        toast.error('Backtest failed');
        setJobId(null);
      }
    }
  }, [polledJob]);

  const symbolOptions = useMemo(() => {
    const symbols = new Set<string>();
    strategies.forEach((strategy) => strategy.symbols.forEach((symbol) => symbols.add(symbol)));
    return Array.from(symbols).sort();
  }, [strategies]);

  const pendingResult = jobSnapshot?.result;

  const handleStart = async () => {
    if (!selectedStrategy) {
      toast.error('Select a strategy');
      return;
    }
    if (!dateRange?.from || !dateRange?.to) {
      toast.error('Select a date range');
      return;
    }

    setSubmitting(true);
    try {
      const response = await startBacktest({
        strategyId: selectedStrategy.id,
        params: overrides,
        symbols: selectedSymbols,
        startDate: dateRange.from.toISOString(),
        endDate: dateRange.to.toISOString(),
        initialCapital,
        feeBps,
        slippageBps,
      });
      setJobId(response.jobId);
      setJobSnapshot(null);
      toast('Backtest started', { description: `Job ${response.jobId}` });
    } catch (error) {
      if (error instanceof Error) {
        toast.error('Unable to start backtest', { description: error.message });
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleSymbolToggle = (symbol: string) => {
    setSelectedSymbols((previous) =>
      previous.includes(symbol)
        ? previous.filter((item) => item !== symbol)
        : [...previous, symbol],
    );
  };

  const handleDownload = (type: 'csv' | 'json') => {
    if (!pendingResult) return;
    if (type === 'json') {
      const blob = new Blob([JSON.stringify(pendingResult, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `backtest-${selectedStrategy?.name ?? 'result'}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      return;
    }

    const trades = pendingResult.trades ?? [];
    const header = 'time,symbol,side,qty,price,pnl';
    const rows = trades.map((trade) =>
      [trade.time, trade.symbol, trade.side, trade.qty, trade.price, trade.pnl ?? ''].join(','),
    );
    const blob = new Blob([`${header}\n${rows.join('\n')}`], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `backtest-${selectedStrategy?.name ?? 'trades'}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 p-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="space-y-4 p-4 lg:col-span-1">
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">Strategy</Label>
            <Select value={selectedStrategyId} onValueChange={setSelectedStrategyId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a strategy" />
              </SelectTrigger>
              <SelectContent>
                {strategies.map((strategy) => (
                  <SelectItem key={strategy.id} value={strategy.id}>
                    {strategy.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">Symbols</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="flex w-full items-center justify-start gap-2">
                  <Filter className="h-4 w-4" />
                  {selectedSymbols.length ? `${selectedSymbols.length} selected` : 'All symbols'}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-60 p-0" align="start">
                <div className="max-h-64 space-y-2 overflow-y-auto p-3">
                  {symbolOptions.map((symbol) => (
                    <label key={symbol} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={selectedSymbols.includes(symbol)}
                        onCheckedChange={() => handleSymbolToggle(symbol)}
                      />
                      <span>{symbol}</span>
                    </label>
                  ))}
                  {symbolOptions.length === 0 && (
                    <p className="text-xs text-muted-foreground">No symbols available</p>
                  )}
                </div>
              </PopoverContent>
            </Popover>
            <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
              {selectedSymbols.map((symbol) => (
                <Badge key={symbol} variant="outline">
                  {symbol}
                </Badge>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">Date Range</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="flex w-full items-center justify-start gap-2">
                  <CalendarIcon className="h-4 w-4" />
                  {dateRange?.from && dateRange?.to
                    ? `${dateRange.from.toLocaleDateString()} – ${dateRange.to.toLocaleDateString()}`
                    : 'Select range'}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="p-0">
                <Calendar
                  mode="range"
                  selected={dateRange}
                  onSelect={setDateRange}
                  numberOfMonths={2}
                  initialFocus
                />
              </PopoverContent>
            </Popover>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Initial Capital</Label>
              <Input
                type="number"
                value={initialCapital}
                onChange={(event) => setInitialCapital(Number(event.target.value) || 0)}
                min={0}
              />
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Fee (bps)</Label>
              <Input
                type="number"
                value={feeBps}
                onChange={(event) => setFeeBps(Number(event.target.value) || 0)}
                min={0}
              />
            </div>
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Slippage (bps)</Label>
              <Input
                type="number"
                value={slippageBps}
                onChange={(event) => setSlippageBps(Number(event.target.value) || 0)}
                min={0}
              />
            </div>
          </div>

          {selectedStrategy && (
            <div className="rounded-lg border border-border p-3">
              <h4 className="mb-2 text-sm font-medium">Parameters</h4>
              <DynamicParamForm
                key={selectedStrategy.id}
                schema={selectedStrategy.paramsSchema}
                initial={selectedStrategy.params}
                submitLabel="Apply Overrides"
                onChange={setOverrides}
                onSubmit={(values) => {
                  setOverrides(values);
                  toast('Overrides saved');
                }}
              />
            </div>
          )}

          <div className="flex items-center gap-2 pt-2">
            <Button
              className="flex-1"
              onClick={handleStart}
              disabled={submitting || !selectedStrategy}
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              <span>{submitting ? 'Starting…' : 'Run Backtest'}</span>
            </Button>
            <Button
              variant="outline"
              size="icon"
              onClick={() => {
                setJobSnapshot(null);
                setJobId(null);
              }}
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
          </div>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-medium">Status</h3>
                <p className="text-xs text-muted-foreground">
                  {jobSnapshot?.status ? jobSnapshot.status.toUpperCase() : jobId ? 'Polling…' : 'Idle'}
                </p>
              </div>
              {jobSnapshot?.progress !== undefined && (
                <Badge variant="outline">{Math.round(jobSnapshot.progress * 100)}%</Badge>
              )}
            </div>
            <div className="mt-4">
              <Progress value={(jobSnapshot?.progress ?? 0) * 100} />
            </div>
            {jobId && (
              <p className="mt-2 text-xs text-muted-foreground">Job: {jobId}</p>
            )}
          </Card>

          {pendingResult && (
            <>
              <Card className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-medium">Summary</h3>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => handleDownload('csv')}>
                      <Download className="mr-2 h-4 w-4" />Trades CSV
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleDownload('json')}>
                      <Download className="mr-2 h-4 w-4" />Full JSON
                    </Button>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
                  <div>
                    <span className="text-muted-foreground">Total Return</span>
                    <p>{(pendingResult.metrics.totalReturn * 100).toFixed(2)}%</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Sharpe</span>
                    <p>{pendingResult.metrics.sharpe.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Max Drawdown</span>
                    <p>{(pendingResult.metrics.maxDrawdown * 100).toFixed(2)}%</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Win Rate</span>
                    <p>{(pendingResult.metrics.winRate * 100).toFixed(1)}%</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Trades</span>
                    <p>{pendingResult.metrics.trades}</p>
                  </div>
                </div>
              </Card>

              <Card className="space-y-4 p-4">
                <h3 className="font-medium">Equity Curve</h3>
                <EquityCurves
                  data={pendingResult.equityCurve.map((point) => ({
                    t: point.t,
                    [selectedStrategy?.name ?? 'Strategy']: point.equity,
                  }))}
                  series={[{ key: selectedStrategy?.name ?? 'Strategy', label: selectedStrategy?.name ?? 'Strategy' }]}
                />
              </Card>

              <div className="grid gap-4 md:grid-cols-2">
                <Card className="space-y-4 p-4">
                  <h3 className="font-medium">PnL by Symbol</h3>
                  <PnlBySymbol data={pendingResult.pnlBySymbol} />
                </Card>
                <Card className="space-y-4 p-4">
                  <h3 className="font-medium">Distribution of Returns</h3>
                  <ReturnsHistogram returns={pendingResult.returns} />
                </Card>
              </div>

              <Card className="p-4">
                <h3 className="mb-3 font-medium">Trades</h3>
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
                    {(pendingResult.trades ?? []).map((trade) => (
                      <TableRow key={`${trade.time}-${trade.symbol}-${trade.price}`}>
                        <TableCell>{new Date(trade.time).toLocaleString()}</TableCell>
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
                </Table>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
