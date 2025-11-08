import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Download, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { getConfigEffective, type ControlRequestOptions, updateConfig } from '../../lib/api';
import { generateIdempotencyKey } from '../../lib/idempotency';
import { queryKeys } from '../../lib/queryClient';
import { useAppStore } from '../../lib/store';
import {
  configEffectiveSchema,
  validateApiResponse,
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
import { Label } from '../ui/label';
import { Skeleton } from '../ui/skeleton';
import { Textarea } from '../ui/textarea';

const CONFIG_FLAGS = [
  {
    key: 'DRY_RUN' as const,
    label: 'Dry Run',
    description: 'Route execution in simulation mode without placing real orders.',
  },
  {
    key: 'SYMBOL_SCANNER_ENABLED' as const,
    label: 'Symbol Scanner',
    description: 'Continuously refresh the universe scanner feed.',
  },
  {
    key: 'SOFT_BREACH_ENABLED' as const,
    label: 'Soft Breach Guard',
    description: 'Alerts and guard-rail for risk rails before hard stops trigger.',
  },
  {
    key: 'SOFT_BREACH_BREAKEVEN_OK' as const,
    label: 'Breakeven Allowed',
    description: 'Permit breakeven exits when a soft breach fires.',
  },
  {
    key: 'SOFT_BREACH_CANCEL_ENTRIES' as const,
    label: 'Cancel Entries',
    description: 'Cancel outstanding entry orders when a soft breach triggers.',
  },
];

export function SettingsTab() {
  const queryClient = useQueryClient();
  const opsToken = useAppStore((state) => state.opsAuth.token);
  const opsActor = useAppStore((state) => state.opsAuth.actor);
  const setOpsToken = useAppStore((state) => state.setOpsToken);
  const setOpsActor = useAppStore((state) => state.setOpsActor);
  const [opsTokenInput, setOpsTokenInput] = useState(opsToken);
  const [opsActorInput, setOpsActorInput] = useState(opsActor);
  const [overrideDraft, setOverrideDraft] = useState('{}');
  const [overrideTouched, setOverrideTouched] = useState(false);

  const configQuery = useQuery({
    queryKey: queryKeys.settings.config(),
    queryFn: () =>
      getConfigEffective().then((data) =>
        validateApiResponse(configEffectiveSchema, data, 'Runtime config')
      ),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (!configQuery.data || overrideTouched) return;
    setOverrideDraft(JSON.stringify(configQuery.data.overrides ?? {}, null, 2));
  }, [configQuery.data, overrideTouched]);

  useEffect(() => {
    setOpsTokenInput(opsToken);
  }, [opsToken]);

  useEffect(() => {
    setOpsActorInput(opsActor);
  }, [opsActor]);

  const tightenPct = useMemo(() => {
    const raw =
      configQuery.data?.effective?.SOFT_BREACH_TIGHTEN_SL_PCT ??
      configQuery.data?.overrides?.SOFT_BREACH_TIGHTEN_SL_PCT;
    return typeof raw === 'number' ? raw : null;
  }, [configQuery.data]);

  const updateMutation = useMutation({
    mutationFn: async ({
      patch,
      options,
    }: {
      patch: Record<string, unknown>;
      options: ControlRequestOptions;
    }) => {
      const response = await updateConfig(patch, options);
      return validateApiResponse(
        configEffectiveSchema,
        response,
        'Updated runtime config'
      );
    },
    onSuccess: (data) => {
      toast.success('Runtime configuration updated');
      setOverrideTouched(false);
      setOverrideDraft(JSON.stringify(data.overrides ?? {}, null, 2));
      queryClient.setQueryData(queryKeys.settings.config(), data);
    },
    onError: (error: unknown) => {
      toast.error('Failed to update configuration', {
        description:
          error instanceof Error ? error.message : 'Unknown error occurred',
      });
    },
  });

  const overridesInvalid = useMemo(() => {
    try {
      const parsed = JSON.parse(overrideDraft || '{}');
      return !(parsed && typeof parsed === 'object' && !Array.isArray(parsed));
    } catch {
      return true;
    }
  }, [overrideDraft]);

  const handleSubmit = () => {
    if (!opsToken.trim()) {
      toast.error('Provide an OPS API token to update configuration');
      return;
    }
    if (!opsActorInput.trim()) {
      toast.error('Provide an operator call-sign for audit logging');
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(overrideDraft || '{}');
    } catch (error) {
      toast.error('Overrides JSON is invalid', {
        description: error instanceof Error ? error.message : undefined,
      });
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      toast.error('Overrides must be a JSON object');
      return;
    }
    updateMutation.mutate({
      patch: parsed as Record<string, unknown>,
      options: {
        token: opsToken.trim(),
        actor: opsActorInput.trim(),
        idempotencyKey: generateIdempotencyKey('config'),
      },
    });
  };

  const handleCopy = async (payload: unknown, label: string) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      toast.success(`${label} copied to clipboard`);
    } catch (error) {
      toast.error(`Unable to copy ${label}`, {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  };

  const handleDownload = (payload: unknown, filename: string) => {
    try {
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error('Download failed', {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  };

  return (
    <div className="space-y-6 p-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>OPS API Token</CardTitle>
            <CardDescription>
              Provide the bearer token required by the Ops API. The value stays in memory only.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => configQuery.refetch()}
            disabled={configQuery.isRefetching}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh config
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="ops-token">X-Ops-Token header</Label>
          <Input
            id="ops-token"
            type="password"
            value={opsTokenInput}
            onChange={(event) => {
              setOpsTokenInput(event.target.value);
              setOpsToken(event.target.value);
            }}
            placeholder="Paste OPS_API_TOKEN value"
            autoComplete="off"
          />
          <p className="text-xs text-zinc-500">
            When running locally, export <code>OPS_API_TOKEN</code> or <code>OPS_API_TOKEN_FILE</code> and reuse that value here for authenticated updates.
          </p>
          <Label htmlFor="ops-actor" className="pt-2">Operator (audit log, required)</Label>
          <Input
            id="ops-actor"
            type="text"
            value={opsActorInput}
            onChange={(event) => {
              setOpsActorInput(event.target.value);
              setOpsActor(event.target.value);
            }}
            placeholder="Enter your call-sign or initials"
            autoComplete="off"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Protection & Automation Flags</CardTitle>
            <CardDescription>
              Values reflect <code>config/runtime.yaml</code> merged with overrides.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                handleCopy(configQuery.data?.overrides ?? {}, 'Overrides JSON')
              }
              disabled={configQuery.isLoading}
            >
              <Copy className="mr-2 h-4 w-4" />
              Copy overrides
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                handleDownload(
                  configQuery.data?.effective ?? {},
                  'runtime-config.json'
                )
              }
              disabled={configQuery.isLoading}
            >
              <Download className="mr-2 h-4 w-4" />
              Download config
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {configQuery.isLoading ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 5 }).map((_, idx) => (
                <Skeleton key={idx} className="h-24 rounded-xl" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {CONFIG_FLAGS.map((flag) => {
                const value =
                  configQuery.data?.effective?.[flag.key] ??
                  configQuery.data?.overrides?.[flag.key];
                const enabled = value === true;
                return (
                  <div
                    key={flag.key}
                    className="rounded-xl border border-zinc-800/60 bg-zinc-900/40 p-4"
                  >
                    <div className="flex items-center justify-between pb-2">
                      <p className="text-sm font-medium text-zinc-200">
                        {flag.label}
                      </p>
                      <Badge
                        variant={enabled ? 'secondary' : 'outline'}
                        className={enabled ? 'bg-emerald-500/10 text-emerald-300' : ''}
                      >
                        {enabled ? 'ENABLED' : 'DISABLED'}
                      </Badge>
                    </div>
                    <p className="text-xs text-zinc-500">{flag.description}</p>
                  </div>
                );
              })}
            </div>
          )}
          <div className="mt-6 rounded-xl border border-zinc-800/60 bg-zinc-900/40 p-4">
            <p className="text-sm font-medium text-zinc-200">
              Soft Breach tighten stop-loss
            </p>
            <p className="text-xs text-zinc-500">
              Percentage applied to tighten the stop-loss when a soft breach occurs.
            </p>
            <div className="mt-3 text-lg font-semibold text-zinc-100">
              {tightenPct !== null ? `${(tightenPct * 100).toFixed(1)}%` : '—'}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Runtime Overrides</CardTitle>
            <CardDescription>
              Edit the JSON payload sent to <code>PUT /api/config</code>.
            </CardDescription>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleSubmit}
            disabled={
              updateMutation.isPending || overridesInvalid || !overrideTouched
            }
          >
            {updateMutation.isPending ? 'Saving…' : 'Save overrides'}
          </Button>
        </CardHeader>
        <CardContent>
          {configQuery.isLoading ? (
            <Skeleton className="h-48 w-full" />
          ) : (
            <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/40 p-4 space-y-3">
              <Textarea
                value={overrideDraft}
                onChange={(event) => {
                  setOverrideDraft(event.target.value);
                  setOverrideTouched(true);
                }}
                className="h-64 font-mono text-xs"
              />
              <p className="text-xs text-zinc-500">
                Example: <code>{'{"DRY_RUN": false, "SOFT_BREACH_ENABLED": true}'}</code>
              </p>
              {overridesInvalid && (
                <p className="text-xs text-amber-400">
                  Overrides must be valid JSON representing an object.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Effective Configuration</CardTitle>
          <CardDescription>
            Resulting payload served to clients (<code>config/runtime.yaml</code> merged with overrides).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {configQuery.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/40 p-4">
              <pre className="max-h-80 overflow-auto text-xs leading-6 text-zinc-300">
                {JSON.stringify(configQuery.data?.effective ?? {}, null, 2)}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-zinc-500">
        Updates apply immediately and are persisted by the Ops service. Keep your token secure; the Command Center never stores it beyond this session.
      </p>
    </div>
  );
}
