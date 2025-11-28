/**
 * Health Monitor Component - System vitals and heartbeat
 * 
 * Monitors WebSocket lag, circuit breakers, and system resources
 */
import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Cpu, HardDrive, Wifi } from 'lucide-react';
import { useSystemHealth, useIsConnected } from '../lib/tradingStore';
import { cn } from '../lib/utils';

export function HealthMonitor() {
    const health = useSystemHealth();
    const isConnected = useIsConnected();
    const [heartbeatLag, setHeartbeatLag] = useState(0);

    // Simulate heartbeat lag (in production, comes from WebSocket)
    useEffect(() => {
        const interval = setInterval(() => {
            setHeartbeatLag(Math.random() * 2); // 0-2 seconds
        }, 1000);
        return () => clearInterval(interval);
    }, []);

    const isHealthy = heartbeatLag < 1 && !health.circuitBreakerTripped && isConnected;

    return (
        <div className="glass-panel p-4">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-cyber-text-dim">System Health</h3>
                <div className={cn('flex items-center gap-2', isHealthy ? 'cyber-positive' : 'cyber-negative')}>
                    {isHealthy ? <Activity className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
                    <span className="text-xs font-semibold">{isHealthy ? 'HEALTHY' : 'DEGRADED'}</span>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
                {/* Heartbeat */}
                <HealthMetric
                    icon={<Wifi className="h-4 w-4" />}
                    label="Heartbeat"
                    value={`${heartbeatLag.toFixed(1)}s`}
                    status={heartbeatLag < 1 ? 'ok' : heartbeatLag < 5 ? 'warn' : 'error'}
                    pulse={heartbeatLag < 1}
                />

                {/* Circuit Breaker */}
                <HealthMetric
                    icon={<AlertTriangle className="h-4 w-4" />}
                    label="Circuit Breaker"
                    value={health.circuitBreakerTripped ? 'TRIPPED' : 'OK'}
                    status={health.circuitBreakerTripped ? 'error' : 'ok'}
                />

                {/* CPU (if available) */}
                {health.cpuPercent !== undefined && (
                    <HealthMetric
                        icon={<Cpu className="h-4 w-4" />}
                        label="CPU"
                        value={`${health.cpuPercent.toFixed(0)}%`}
                        status={health.cpuPercent < 70 ? 'ok' : health.cpuPercent < 90 ? 'warn' : 'error'}
                    />
                )}

                {/* Memory (if available) */}
                {health.memoryMb !== undefined && (
                    <HealthMetric
                        icon={<HardDrive className="h-4 w-4" />}
                        label="Memory"
                        value={`${(health.memoryMb / 1024).toFixed(1)}GB`}
                        status={health.memoryMb < 2048 ? 'ok' : health.memoryMb < 3072 ? 'warn' : 'error'}
                    />
                )}

                {/* Rate Limit (if available) */}
                {health.rateLimitUsage !== undefined && (
                    <div className="col-span-2">
                        <div className="text-xs text-cyber-text-dim mb-2">API Rate Limit</div>
                        <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 bg-cyber-glass-bg rounded-full overflow-hidden">
                                <div
                                    className={cn(
                                        'h-full transition-all',
                                        health.rateLimitUsage < 70
                                            ? 'bg-cyber-accent'
                                            : health.rateLimitUsage < 90
                                                ? 'bg-cyber-neutral'
                                                : 'bg-cyber-negative'
                                    )}
                                    style={{ width: `${health.rateLimitUsage}%` }}
                                />
                            </div>
                            <span className="text-xs font-mono w-12 text-right">{health.rateLimitUsage}%</span>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

function HealthMetric({
    icon,
    label,
    value,
    status,
    pulse = false,
}: {
    icon: React.ReactNode;
    label: string;
    value: string;
    status: 'ok' | 'warn' | 'error';
    pulse?: boolean;
}) {
    const statusColor =
        status === 'ok' ? 'cyber-positive' : status === 'warn' ? 'cyber-neutral' : 'cyber-negative';

    return (
        <div className="flex items-center gap-3">
            <div className={cn(statusColor, pulse && 'cyber-pulse')}>{icon}</div>
            <div className="flex-1 min-w-0">
                <div className="text-xs text-cyber-text-dim">{label}</div>
                <div className={cn('text-sm font-mono font-semibold truncate', statusColor)}>{value}</div>
            </div>
        </div>
    );
}
