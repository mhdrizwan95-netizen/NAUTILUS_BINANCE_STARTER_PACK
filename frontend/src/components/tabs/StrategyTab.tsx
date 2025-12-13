import { Play, Square, Settings2, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { DynamicParamForm } from "@/components/forms/DynamicParamForm";
import { MiniChart } from "@/components/MiniChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  getStrategies,
  startStrategy,
  stopStrategy,
  updateStrategy,
  type PageMetadata,
} from "@/lib/api";
import { generateIdempotencyKey } from "@/lib/idempotency";
import { useAppStore } from "@/lib/store";
import { useTradingStore } from "@/lib/tradingStore";
import type { StrategySummary } from "@/types/trading";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

const STRATEGY_CARD_CLASS =
  "rounded-2xl border border-zinc-800/60 bg-zinc-950/40 backdrop-blur-sm shadow-lg shadow-black/10";

export function StrategyTab() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [configureTarget, setConfigureTarget] = useState<StrategySummary | null>(null);
  const opsToken = useAppStore((state) => state.opsAuth.token);
  const opsActor = useAppStore((state) => state.opsAuth.actor);
  const [pageInfo, setPageInfo] = useState<PageMetadata | null>(null);

  // Subscribe to live updates
  const liveStrategies = useTradingStore((state) => state.strategies);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await getStrategies();
      setStrategies(payload.data);
      setPageInfo(payload.page ?? null);
    } catch (error) {
      if (error instanceof Error) {
        toast.error("Unable to load strategies", { description: error.message });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMore = async () => {
    if (!pageInfo?.nextCursor) return;
    setLoading(true);
    try {
      const payload = await getStrategies({ cursor: pageInfo.nextCursor });
      setStrategies((prev) => [...prev, ...payload.data]);
      setPageInfo(payload.page ?? null);
    } catch (error) {
      if (error instanceof Error) {
        toast.error("Unable to load additional strategies", { description: error.message });
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPageInfo(null);
    void refresh();
  }, [refresh]);

  const requireCredentials = () => {
    if (!opsToken.trim()) {
      toast.error("Set OPS API token in Settings before issuing control actions");
      return false;
    }
    if (!opsActor.trim()) {
      toast.error("Provide an operator call-sign before issuing control actions");
      return false;
    }
    return true;
  };

  const buildControlOptions = (prefix: string) => ({
    token: opsToken.trim(),
    actor: opsActor.trim(),
    idempotencyKey: generateIdempotencyKey(prefix),
  });

  const handleDryRunToggle = async (strategy: StrategySummary, enabled: boolean) => {
    if (!requireCredentials()) {
      return;
    }
    setBusyId(strategy.id);
    try {
      const nextParams = { ...(strategy.params ?? {}), dry_run: enabled };
      await updateStrategy(strategy.id, nextParams, buildControlOptions(`dryrun-${strategy.id}`));
      toast.success(`Dry run ${enabled ? "enabled" : "disabled"} for ${strategy.name}`);
      await refresh();
    } catch (error) {
      if (error instanceof Error) {
        toast.error("Failed to toggle dry run", { description: error.message });
      }
    } finally {
      setBusyId(null);
    }
  };

  const handleStart = async (strategy: StrategySummary) => {
    if (!requireCredentials()) {
      return;
    }
    setBusyId(strategy.id);
    try {
      await startStrategy(
        strategy.id,
        strategy.params,
        buildControlOptions(`start-${strategy.id}`),
      );
      toast.success(`Started ${strategy.name}`);
      await refresh();
    } catch (error) {
      if (error instanceof Error) {
        toast.error("Failed to start strategy", { description: error.message });
      }
    } finally {
      setBusyId(null);
    }
  };

  const handleStop = async (strategy: StrategySummary) => {
    if (!requireCredentials()) {
      return;
    }
    setBusyId(strategy.id);
    try {
      await stopStrategy(strategy.id, buildControlOptions(`stop-${strategy.id}`));
      toast("Strategy stopped", { description: strategy.name });
      await refresh();
    } catch (error) {
      if (error instanceof Error) {
        toast.error("Failed to stop strategy", { description: error.message });
      }
    } finally {
      setBusyId(null);
    }
  };

  const appliedStrategies = useMemo(() => strategies, [strategies]);

  return (
    <div className="space-y-6 p-6">
      {loading && strategies.length === 0 ? (
        <div className="text-sm text-muted-foreground">Loading strategies…</div>
      ) : null}

      {pageInfo?.totalHint !== undefined ? (
        <div className="text-xs text-muted-foreground">
          Showing {strategies.length} of {pageInfo.totalHint ?? "∞"} strategies
        </div>
      ) : null}

      {/* DEBUG OVERLAY */}
      <div className="rounded-lg border border-yellow-500/50 bg-yellow-500/10 p-4 text-xs font-mono text-yellow-200 mb-4 overflow-x-auto">
        <h4 className="font-bold border-b border-yellow-500/30 mb-2 pb-1">TELEMETRY DEBUGGER v3 (DATA INSPECT)</h4>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-yellow-500/20">
              <th>Key</th>
              <th>ID</th>
              <th>Name</th>
              <th>PnL</th>
              <th>Conf</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(liveStrategies.entries()).map(([key, strat]) => (
              <tr key={key} className="border-b border-yellow-500/10">
                <td className="py-1 pr-2 text-zinc-400">{key}</td>
                <td className="py-1 pr-2 text-blue-300">{strat.id || "MISSING"}</td>
                <td className="py-1 pr-2 text-zinc-300 truncate max-w-[100px]">{strat.name}</td>
                <td className="py-1 pr-2 text-green-300">{strat.performance?.pnl?.toFixed(2) ?? "NULL"}</td>
                <td className="py-1 text-purple-300">{strat.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {appliedStrategies.map((strategy) => {
          const liveState = liveStrategies.get(strategy.id);
          const performance = liveState?.performance ?? strategy.performance;

          // Debug fallback if performance is missing
          // console.log(`Rendering ${strategy.id}`, { live: liveState, static: strategy });

          const perfAny = performance as any;
          const trend: "up" | "down" | "neutral" = perfAny?.equitySeries?.length
            ? perfAny.equitySeries.at(-1)!.equity >= perfAny.equitySeries[0].equity
              ? "up"
              : "down"
            : "neutral";
          const sparkline = perfAny?.equitySeries?.map((point: any) => point.equity) ?? [];
          const pnlValue = performance?.pnl ?? 0;

          // Use live status if available, otherwise static
          const status = liveState ? (liveState.enabled ? "running" : "stopped") : strategy.status;

          const statusAdornment =
            status === "running"
              ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-300"
              : status === "error"
                ? "border-red-400/40 bg-red-500/10 text-red-300"
                : "border-zinc-700 bg-zinc-900 text-zinc-400";

          return (
            <Card
              key={strategy.id}
              className={`${STRATEGY_CARD_CLASS} flex flex-col gap-5 p-5 min-h-[360px]`}
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-12 w-12 items-center justify-center rounded-xl border ${statusAdornment}`}
                  >
                    <Zap className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-semibold">{strategy.name}</h3>
                      <Badge
                        variant={
                          strategy.status === "running"
                            ? "secondary"
                            : strategy.status === "error"
                              ? "destructive"
                              : "outline"
                        }
                        className="text-[11px]"
                      >
                        {strategy.status.toUpperCase()}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {strategy.kind} • {strategy.symbols.join(", ")}
                    </p>
                  </div>
                </div>
                <div className="flex h-20 min-w-[200px] flex-1 items-center justify-center rounded-xl border border-zinc-800/70 bg-zinc-950/40 p-3 sm:max-w-[240px]">
                  {sparkline.length > 1 ? (
                    <MiniChart
                      data={sparkline}
                      color={trend === "up" ? "#10b981" : trend === "down" ? "#ef4444" : "#6366f1"}
                      trend={trend}
                    />
                  ) : (
                    <div className="text-xs text-muted-foreground">No data</div>
                  )}
                </div>
              </div>

              <div className="grid gap-3 text-center text-xs sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border border-zinc-800/60 bg-zinc-950/40 p-3">
                  <p className="text-[10px] uppercase text-zinc-500">PnL</p>
                  <p
                    className={`font-mono text-sm ${pnlValue >= 0 ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {formatCurrency(pnlValue)}
                  </p>
                </div>
                <div className="rounded-xl border border-zinc-800/60 bg-zinc-950/40 p-3">
                  <p className="text-[10px] uppercase text-zinc-500">Win Rate</p>
                  <p className="font-mono text-sm text-zinc-100">
                    {performance?.winRate !== undefined
                      ? `${(performance.winRate * 100).toFixed(1)}%`
                      : "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-zinc-800/60 bg-zinc-950/40 p-3">
                  <p className="text-[10px] uppercase text-zinc-500">Sharpe</p>
                  <p className="font-mono text-sm text-zinc-100">
                    {performance?.sharpe !== undefined ? performance.sharpe.toFixed(2) : "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-zinc-800/60 bg-zinc-950/40 p-3">
                  <p className="text-[10px] uppercase text-zinc-500">Drawdown</p>
                  <p className="font-mono text-sm text-zinc-100">
                    {performance?.drawdown !== undefined
                      ? `${(performance.drawdown * 100).toFixed(1)}%`
                      : "—"}
                  </p>
                </div>
              </div>

              <div className="rounded-xl border border-zinc-800/60 bg-black/20 p-4 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-zinc-200">Dry run mode</p>
                    <p className="text-zinc-500">Simulate orders without placing live trades.</p>
                  </div>
                  <Switch
                    checked={Boolean(strategy.params?.dry_run)}
                    disabled={busyId === strategy.id}
                    onCheckedChange={(value) => handleDryRunToggle(strategy, value)}
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3 border-t border-zinc-800/60 pt-4">
                {strategy.status !== "running" ? (
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

      {pageInfo?.nextCursor ? (
        <div className="flex justify-center">
          <Button onClick={loadMore} disabled={loading} variant="outline">
            {loading ? "Loading…" : "Load older strategies"}
          </Button>
        </div>
      ) : null}

      <Dialog
        open={configureTarget !== null}
        onOpenChange={(open) => !open && setConfigureTarget(null)}
      >
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
                if (!requireCredentials()) {
                  return;
                }
                setBusyId(configureTarget.id);
                try {
                  await updateStrategy(
                    configureTarget.id,
                    values,
                    buildControlOptions(`update-${configureTarget.id}`),
                  );
                  toast.success("Strategy updated");
                  setConfigureTarget(null);
                  await refresh();
                } catch (error) {
                  if (error instanceof Error) {
                    toast.error("Failed to update strategy", { description: error.message });
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
