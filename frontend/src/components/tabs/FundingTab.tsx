import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { TrendingUp, DollarSign, BarChart2, Save } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import {
  getAggregatePortfolio,
  getAggregateExposure,
  getAggregatePnl,
  getConfigEffective,
  updateConfig,
  type ControlRequestOptions,
} from '../../lib/api';
import { generateIdempotencyKey } from '../../lib/idempotency';
import { queryKeys } from '../../lib/queryClient';
import { useAppStore } from '../../lib/store';
import {
  exposureAggregateSchema,
  pnlSnapshotSchema,
  portfolioAggregateSchema,
  validateApiResponse,
  configEffectiveSchema,
} from '../../lib/validation';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../ui/card';
import { Input } from '../ui/input';
import { Skeleton } from '../ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';

function formatCurrency(value: number, opts: Intl.NumberFormatOptions = {}) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    ...opts,
  }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatEpoch(epoch: number | null | undefined) {
  if (!epoch) return '—';
  const date = new Date(epoch * 1000);
  return date.toLocaleString();
}

export function FundingTab() {
  const queryClient = useQueryClient();
  const opsToken = useAppStore((state) => state.opsAuth.token);
  const opsActor = useAppStore((state) => state.opsAuth.actor);

  const portfolioQuery = useQuery({
    queryKey: queryKeys.funding.portfolio(),
    queryFn: () =>
      getAggregatePortfolio().then((data) =>
        validateApiResponse(portfolioAggregateSchema, data, 'Aggregate portfolio'),
      ),
    refetchInterval: 30_000,
  });

  const exposureQuery = useQuery({
    queryKey: queryKeys.funding.exposure(),
    queryFn: () =>
      getAggregateExposure().then((data) =>
        validateApiResponse(exposureAggregateSchema, data, 'Exposure aggregate'),
      ),
    refetchInterval: 30_000,
  });

  const pnlQuery = useQuery({
    queryKey: queryKeys.funding.pnl(),
    queryFn: () =>
      getAggregatePnl().then((data) =>
        validateApiResponse(pnlSnapshotSchema, data, 'PnL snapshot'),
      ),
    refetchInterval: 30_000,
  });

  const configQuery = useQuery({
    queryKey: queryKeys.settings.config(),
    queryFn: () =>
      getConfigEffective().then((data) =>
        validateApiResponse(configEffectiveSchema, data, 'Runtime config'),
      ),
    staleTime: 60_000,
  });

  const [budgetDraft, setBudgetDraft] = useState<Record<string, number>>({});
  const [budgetTouched, setBudgetTouched] = useState(false);

  useEffect(() => {
    if (!configQuery.data || budgetTouched) return;
    const buckets = configQuery.data.effective?.buckets ?? {};
    const mapped = Object.entries(buckets).reduce<Record<string, number>>((acc, [key, val]) => {
      acc[key] = typeof val === 'number' ? val : Number(val ?? 0);
      return acc;
    }, {});
    setBudgetDraft(mapped);
  }, [configQuery.data, budgetTouched]);

  const updateBudgetsMutation = useMutation({
    mutationFn: async ({
      buckets,
      options,
    }: {
      buckets: Record<string, number>;
      options: ControlRequestOptions;
    }) => updateConfig({ buckets }, options),
    onSuccess: (data) => {
      toast.success('Capital buckets updated');
      setBudgetTouched(false);
      const buckets = data.effective?.buckets ?? {};
      const mapped = Object.entries(buckets).reduce<Record<string, number>>((acc, [key, val]) => {
        acc[key] = typeof val === 'number' ? val : Number(val ?? 0);
        return acc;
      }, {});
      setBudgetDraft(mapped);
      queryClient.setQueryData(queryKeys.settings.config(), data);
    },
    onError: (error: unknown) => {
      toast.error('Failed to update capital buckets', {
        description: error instanceof Error ? error.message : 'Unknown error',
      });
    },
  });

  const handleBudgetChange = (bucket: string, value: number) => {
    setBudgetTouched(true);
    setBudgetDraft((prev) => ({ ...prev, [bucket]: value }));
  };

  const totalBudget = useMemo(
    () => Object.values(budgetDraft).reduce((sum, value) => sum + (Number(value) || 0), 0),
    [budgetDraft],
  );

  const exposureRows = useMemo(() => {
    if (!exposureQuery.data) return [];
    return Object.entries(exposureQuery.data.by_symbol)
      .map(([key, value]) => {
        const [symbol, venue = 'UNKNOWN'] = key.split('.');
        return {
          key,
          symbol,
          venue,
          qty: value.qty_base,
          price: value.last_price_usd,
          exposure: value.exposure_usd,
        };
      })
      .sort((a, b) => Math.abs(b.exposure) - Math.abs(a.exposure))
      .slice(0, 12);
  }, [exposureQuery.data]);

  const pnlRows = useMemo(() => {
    if (!pnlQuery.data) return [];
    const venues = new Set([
      ...Object.keys(pnlQuery.data.realized),
      ...Object.keys(pnlQuery.data.unrealized),
    ]);
    return Array.from(venues)
      .map((venue) => {
        const realized = pnlQuery.data.realized[venue] ?? 0;
        const unrealized = pnlQuery.data.unrealized[venue] ?? 0;
        return {
          venue,
          realized,
          unrealized,
          total: realized + unrealized,
        };
      })
      .sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
  }, [pnlQuery.data]);

  const isExposureLoading =
    portfolioQuery.isLoading || exposureQuery.isLoading || pnlQuery.isLoading;

  return (
    <div className="space-y-6 p-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Capital Buckets</CardTitle>
            <CardDescription>
              Update allocation weights used by the allocator. Values must sum to 1.0.
            </CardDescription>
          </div>
          <Button
            variant="secondary"
            size="sm"
            disabled={
              updateBudgetsMutation.isPending ||
              !budgetTouched ||
              !opsToken.trim() ||
              !opsActor.trim() ||
              Math.abs(totalBudget - 1) > 0.001
            }
            onClick={() => {
              if (!opsToken.trim()) {
                toast.error('Provide an OPS token in Settings before updating buckets');
                return;
              }
              if (!opsActor.trim()) {
                toast.error('Provide an operator call-sign before updating capital buckets');
                return;
              }
              updateBudgetsMutation.mutate({
                buckets: budgetDraft,
                options: {
                  token: opsToken.trim(),
                  actor: opsActor.trim(),
                  idempotencyKey: generateIdempotencyKey('buckets'),
                },
              });
            }}
          >
            <Save className="mr-2 h-4 w-4" />
            {updateBudgetsMutation.isPending ? 'Saving…' : 'Save allocations'}
          </Button>
        </CardHeader>
        <CardContent>
          {configQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                {Object.entries(budgetDraft).map(([bucket, value]) => (
                  <div
                    key={bucket}
                    className="rounded-lg border border-zinc-800/60 bg-zinc-950/40 p-4 space-y-2"
                  >
                    <div className="flex items-center justify-between text-sm font-medium text-zinc-200">
                      <span>{bucket}</span>
                      <span>{(value * 100).toFixed(1)}%</span>
                    </div>
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={Number.isFinite(value) ? value : 0}
                      onChange={(event) => handleBudgetChange(bucket, Number(event.target.value))}
                    />
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between text-xs text-zinc-500">
                <span>Total allocation</span>
                <span
                  className={
                    Math.abs(totalBudget - 1) <= 0.001 ? 'text-emerald-400' : 'text-amber-400'
                  }
                >
                  {totalBudget.toFixed(3)}
                </span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-4 md:grid md:grid-cols-3">
        <MetricCard
          title="Total Equity"
          description="Aggregate across all venues"
          icon={<TrendingUp className="h-4 w-4 text-emerald-400" />}
          value={
            portfolioQuery.data ? formatCurrency(portfolioQuery.data.equity_usd) : '—'
          }
          footer={
            portfolioQuery.data
              ? `Return: ${formatPercent(portfolioQuery.data.return_pct)}`
              : 'Return: —'
          }
          loading={portfolioQuery.isLoading}
        />
        <MetricCard
          title="Cash on Hand"
          description="Liquid capital available"
          icon={<DollarSign className="h-4 w-4 text-cyan-400" />}
          value={
            portfolioQuery.data ? formatCurrency(portfolioQuery.data.cash_usd) : '—'
          }
          footer={
            portfolioQuery.data
              ? `Gain/Loss: ${formatCurrency(portfolioQuery.data.gain_usd)}`
              : 'Gain/Loss: —'
          }
          loading={portfolioQuery.isLoading}
        />
        <MetricCard
          title="Tracked Symbols"
          description="Positions & watchlist coverage"
          icon={<BarChart2 className="h-4 w-4 text-violet-400" />}
          value={exposureQuery.data ? exposureQuery.data.totals.count.toString() : '—'}
          footer={
            exposureQuery.data
              ? `Exposure: ${formatCurrency(exposureQuery.data.totals.exposure_usd, {
                  maximumFractionDigits: 0,
                  minimumFractionDigits: 0,
                })}`
              : 'Exposure: —'
          }
          loading={exposureQuery.isLoading}
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <div>
            <CardTitle>Symbol Exposure</CardTitle>
            <CardDescription>Top positions by notional exposure (USD)</CardDescription>
          </div>
          <Badge variant="outline">
            Last refresh: {formatEpoch(portfolioQuery.data?.last_refresh_epoch)}
          </Badge>
        </CardHeader>
        <CardContent>
          {isExposureLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : exposureRows.length === 0 ? (
            <EmptyState message="No exposure data available yet. Once positions are reported by the engines they will appear here." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Venue</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="text-right">Last Price</TableHead>
                    <TableHead className="text-right">Exposure</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {exposureRows.map((row) => (
                    <TableRow key={row.key}>
                      <TableCell>{row.symbol}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">{row.venue}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {row.qty.toFixed(6)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatCurrency(row.price)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatCurrency(row.exposure, {
                          maximumFractionDigits: 0,
                          minimumFractionDigits: 0,
                        })}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Venue PnL Snapshot</CardTitle>
          <CardDescription>Realized vs unrealized performance by venue</CardDescription>
        </CardHeader>
        <CardContent>
          {pnlQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : pnlRows.length === 0 ? (
            <EmptyState message="PnL data is not available yet. Populate the collectors or run the engines to see live figures." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Venue</TableHead>
                    <TableHead className="text-right">Realized</TableHead>
                    <TableHead className="text-right">Unrealized</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pnlRows.map((row) => {
                    const positive = row.total >= 0;
                    return (
                      <TableRow key={row.venue}>
                        <TableCell>
                          <Badge variant="outline">{row.venue}</Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCurrency(row.realized)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCurrency(row.unrealized)}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono ${
                            positive ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {formatCurrency(row.total)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

type MetricCardProps = {
  title: string;
  description: string;
  value: string;
  icon: React.ReactNode;
  footer?: string;
  loading?: boolean;
};

function MetricCard({ title, description, value, icon, footer, loading }: MetricCardProps) {
  return (
    <Card className="bg-zinc-900/40 border-zinc-800">
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <div>
          <CardTitle className="text-sm text-zinc-200">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <div className="rounded-full border border-zinc-700/50 bg-zinc-900/70 p-2">
          {icon}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-36" />
        ) : (
          <div className="text-2xl font-semibold text-zinc-100">{value}</div>
        )}
        {footer ? <p className="mt-2 text-xs text-zinc-500">{footer}</p> : null}
      </CardContent>
    </Card>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-dashed border-zinc-800 bg-zinc-900/40 px-4 text-sm text-zinc-500">
      {message}
    </div>
  );
}
