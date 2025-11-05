import { memo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Skeleton } from './ui/skeleton';

type OpsCommand = 'pause' | 'resume' | 'flatten' | 'kill' | 'config';

export interface OpsPanelSkeletonProps {
  /** Whether the operator supplied X-Ops-Token + two-man approvals */
  isAuthorized: boolean;
  tradingEnabled?: boolean;
  loading?: boolean;
  onCommand?: (command: OpsCommand) => void;
}

/**
 * Bare-bones layout that mirrors the Command Center control affordances.
 * Intended as a design scaffold when composing the real Ops dashboard.
 */
export const OpsPanelSkeleton = memo(
  ({ isAuthorized, tradingEnabled = true, loading = false, onCommand }: OpsPanelSkeletonProps) => (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
      <Card className="border border-zinc-800/60 bg-zinc-950/50">
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle className="text-zinc-100 tracking-wide uppercase">Control Plane</CardTitle>
            <p className="text-xs text-zinc-500">
              Pause, resume, flatten, and emergency stop actions proxy to the Ops API.
            </p>
          </div>
          <Badge variant={tradingEnabled ? 'secondary' : 'destructive'}>
            {tradingEnabled ? 'Trading enabled' : 'Trading paused'}
          </Badge>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Button
            variant="outline"
            className="justify-start gap-2"
            disabled={!isAuthorized || loading || !tradingEnabled}
            onClick={() => onCommand?.('pause')}
          >
            Pause trading
          </Button>
          <Button
            variant="outline"
            className="justify-start gap-2"
            disabled={!isAuthorized || loading || tradingEnabled}
            onClick={() => onCommand?.('resume')}
          >
            Resume trading
          </Button>
          <Button
            variant="outline"
            className="justify-start gap-2"
            disabled={!isAuthorized || loading}
            onClick={() => onCommand?.('flatten')}
          >
            Flatten positions
          </Button>
          <Button
            variant="destructive"
            className="justify-start gap-2"
            disabled={!isAuthorized || loading}
            onClick={() => onCommand?.('kill')}
          >
            Emergency stop
          </Button>
        </CardContent>
      </Card>

      <Card className="border border-zinc-800/60 bg-zinc-950/50">
        <CardHeader>
          <CardTitle className="text-sm text-zinc-200">Runtime Overrides</CardTitle>
          <p className="text-xs text-zinc-500">
            Mirrors the JSON payload sent to <code>PUT /api/config</code>.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-4 w-full rounded" />
          <Skeleton className="h-4 w-9/12 rounded" />
          <Button
            size="sm"
            className="w-full justify-center"
            disabled={!isAuthorized || loading}
            onClick={() => onCommand?.('config')}
          >
            Save config overrides
          </Button>
        </CardContent>
      </Card>
    </div>
  )
);

OpsPanelSkeleton.displayName = 'OpsPanelSkeleton';
