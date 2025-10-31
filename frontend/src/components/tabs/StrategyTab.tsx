import { useEffect, useMemo, useState } from 'react';
import { Play, Square, Settings2 } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { DynamicParamForm } from '@/components/forms/DynamicParamForm';
import { MiniChart } from '@/components/MiniChart';
import {
  getStrategies,
  startStrategy,
  stopStrategy,
  updateStrategy,
} from '@/lib/api';
import type { StrategySummary } from '@/types/trading';

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

export function StrategyTab() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [configureTarget, setConfigureTarget] = useState<StrategySummary | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const payload = await getStrategies();
      setStrategies(payload);
    } catch (error) {
      if (error instanceof Error) {
        toast.error('Unable to load strategies', { description: error.message });
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleStart = async (strategy: StrategySummary) => {
    setBusyId(strategy.id);
    try {
      await startStrategy(strategy.id, strategy.params);
      toast.success(`Started ${strategy.name}`);
      await refresh();
    } catch (error) {
      if (error instanceof Error) {
        toast.error('Failed to start strategy', { description: error.message });
      }
    } finally {
      setBusyId(null);
    }
  };

  const handleStop = async (strategy: StrategySummary) => {
    setBusyId(strategy.id);
    try {
      await stopStrategy(strategy.id);
      toast('Strategy stopped', { description: strategy.name });
      await refresh();
    } catch (error) {
      if (error instanceof Error) {
        toast.error('Failed to stop strategy', { description: error.message });
      }
    } finally {
      setBusyId(null);
    }
  };

  const appliedStrategies = useMemo(() => strategies, [strategies]);

  return (
    <div className="space-y-4 p-6">
      {loading && strategies.length === 0 ? (
        <div className="text-sm text-muted-foreground">Loading strategies…</div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {appliedStrategies.map((strategy) => {
          const performance = strategy.performance;
          const trend: 'up' | 'down' | 'neutral' = performance?.equitySeries?.length
            ? performance.equitySeries.at(-1)!.equity >= performance.equitySeries[0].equity
              ? 'up'
              : 'down'
            : 'neutral';
          const sparkline = performance?.equitySeries?.map((point) => point.equity) ?? [];
          const pnlValue = performance?.pnl ?? 0;

          return (
            <Card key={strategy.id} className="flex flex-col gap-4 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold">{strategy.name}</h3>
                    <Badge
                      variant={
                        strategy.status === 'running'
                          ? 'secondary'
                          : strategy.status === 'error'
                          ? 'destructive'
                          : 'outline'
                      }
                    >
                      {strategy.status.toUpperCase()}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {strategy.kind} • {strategy.symbols.join(', ')}
                  </p>
                </div>
                <div className="h-16 w-40">
                  {sparkline.length > 1 ? (
                    <MiniChart
                      data={sparkline}
                      color={trend === 'up' ? '#10b981' : trend === 'down' ? '#ef4444' : '#6366f1'}
                      trend={trend}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                      No data
                    </div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-muted-foreground">PnL</span>
                  <p className={pnlValue >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                    {formatCurrency(pnlValue)}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Win Rate</span>
                  <p>{performance?.winRate !== undefined ? `${(performance.winRate * 100).toFixed(1)}%` : '—'}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Sharpe</span>
                  <p>{performance?.sharpe !== undefined ? performance.sharpe.toFixed(2) : '—'}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Drawdown</span>
                  <p>
                    {performance?.drawdown !== undefined
                      ? `${(performance.drawdown * 100).toFixed(1)}%`
                      : '—'}
                  </p>
                </div>
              </div>

              <Separator />

              <div className="flex items-center gap-2">
                {strategy.status !== 'running' ? (
                  <Button
                    size="sm"
                    onClick={() => handleStart(strategy)}
                    disabled={busyId === strategy.id}
                    className="flex items-center gap-2"
                  >
                    <Play className="h-4 w-4" />
                    Start
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => handleStop(strategy)}
                    disabled={busyId === strategy.id}
                    className="flex items-center gap-2"
                  >
                    <Square className="h-4 w-4" />
                    Stop
                  </Button>
                )}

                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfigureTarget(strategy)}
                  className="flex items-center gap-2"
                >
                  <Settings2 className="h-4 w-4" />
                  Configure
                </Button>
              </div>
            </Card>
          );
        })}
      </div>

      <Dialog open={configureTarget !== null} onOpenChange={(open) => !open && setConfigureTarget(null)}>
        <DialogContent className="max-w-xl">
          {configureTarget && (
            <DialogHeader>
              <DialogTitle>Configure {configureTarget.name}</DialogTitle>
              <DialogDescription>
                Update parameters and apply instantly. Changes propagate on the next signal tick.
              </DialogDescription>
            </DialogHeader>
          )}
          {configureTarget && (
            <DynamicParamForm
              schema={configureTarget.paramsSchema}
              initial={configureTarget.params}
              submitLabel="Save"
              onSubmit={async (values) => {
                setBusyId(configureTarget.id);
                try {
                  await updateStrategy(configureTarget.id, values);
                  toast.success('Strategy updated');
                  setConfigureTarget(null);
                  await refresh();
                } catch (error) {
                  if (error instanceof Error) {
                    toast.error('Failed to update strategy', { description: error.message });
                  }
                } finally {
                  setBusyId(null);
                }
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
