/**
 * Health Monitor Component - "SYSTEM INTERNALS"
 * 
 * Engineering view: Latency, Docker health, and API limits.
 */
import { Activity, Cpu, HardDrive, Server, Database } from 'lucide-react';
import { useEffect, useState } from 'react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';

import { cn } from '../lib/utils';
import { useAppStore } from '../lib/store';
import { GlassCard } from './ui/GlassCard';
import { LatencyHeatmap } from './LatencyHeatmap';

export function HealthMonitor() {
    // Simulated Health State
    const [heartbeatHistory, setHeartbeatHistory] = useState<{ i: number; v: number }[]>([]);
    // const [latencyMap, setLatencyMap] = useState<number[]>(Array(50).fill(0)); // Removed mock
    const [logs] = useState<string[]>([]); // TODO: Wire to store logs
    // const [apiWeight, setApiWeight] = useState(450);

    // Simulation Loop
    const lastHeartbeat = useAppStore(state => state.realTimeData.lastHeartbeat);
    // Real Heartbeat History derived from store updates
    useEffect(() => {
        if (!lastHeartbeat) return;
        setHeartbeatHistory(prev => {
            const newPoint = { i: Date.now(), v: 1 }; // Simple pulse
            return [...prev, newPoint].slice(-50);
        });
    }, [lastHeartbeat]);

    return (
        <div className="p-8 space-y-8 min-h-screen flex flex-col bg-deep-space text-zinc-100 font-header pb-20">

            {/* STATUS HEADER */}
            <div className="grid grid-cols-4 gap-6 shrink-0">
                <StatusBadge label="ENGINE" status="OK" color="green" />
                <StatusBadge label="DATA FEED" status="OK" color="green" />
                <StatusBadge label="EXECUTION" status="OK" color="green" />
                <StatusBadge label="ML TRAINING" status="TRAINING" color="amber" />
            </div>

            {/* MAIN METRICS ROW */}
            <div className="grid grid-cols-3 gap-8 h-[350px]">

                {/* API Weight Radial */}
                {/* API Weight - Placeholder for future real data or remove */}
                <GlassCard title="API Weight" neonAccent="green" className="flex flex-col items-center justify-center">
                    <div className="text-zinc-500 text-sm">No Telemetry</div>
                </GlassCard>

                {/* Order Latency Heatmap */}
                <LatencyHeatmap />

                {/* Watchdog Heartbeat */}
                <GlassCard title="Watchdog Heartbeat" neonAccent="green" className="flex flex-col">
                    <div className="flex-1 w-full min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={heartbeatHistory}>
                                <YAxis domain={[0, 2]} hide />
                                <Line
                                    type="step"
                                    dataKey="v"
                                    stroke="#00ff9d"
                                    strokeWidth={2}
                                    dot={false}
                                    isAnimationActive={false}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                    <div className="text-center text-xs text-neon-green font-mono mt-2 animate-pulse">
                        {lastHeartbeat
                            ? `SYSTEM HEALTHY • LAST TICK: ${new Date(lastHeartbeat).toLocaleTimeString()}`
                            : 'WAITING FOR HEARTBEAT...'}
                    </div>
                </GlassCard>
            </div>

            {/* BOTTOM ROW: Resources & Logs */}
            <div className="grid grid-cols-3 gap-8 h-[300px]">

                {/* Docker Resources */}
                <GlassCard title="Docker Resources" neonAccent="cyan" className="flex flex-col justify-around">
                    <div className="flex items-center gap-4">
                        <Cpu className="w-8 h-8 text-neon-cyan" />
                        <div className="flex-1">
                            <div className="flex justify-between mb-1">
                                <span className="text-sm text-zinc-400">CPU Usage</span>
                                <span className="text-sm font-bold text-white">12%</span>
                            </div>
                            <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-neon-cyan w-[12%]" />
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-4">
                        <HardDrive className="w-8 h-8 text-neon-blue" />
                        <div className="flex-1">
                            <div className="flex justify-between mb-1">
                                <span className="text-sm text-zinc-400">RAM Usage</span>
                                <span className="text-sm font-bold text-white">2.4GB</span>
                            </div>
                            <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-neon-blue w-[40%]" />
                            </div>
                        </div>
                    </div>
                </GlassCard>

                {/* Error Log Stream */}
                <GlassCard title="System Log Stream" neonAccent="amber" className="col-span-1 flex flex-col">
                    <div className="flex-1 overflow-hidden font-mono text-xs space-y-2">
                        {logs.length === 0 ? (
                            <div className="text-zinc-500 italic p-2">No active system logs captured.</div>
                        ) : logs.map((log, i) => (
                            <div key={i} className={cn(
                                "truncate",
                                log.includes("WARN") ? "text-neon-amber" :
                                    log.includes("ERROR") ? "text-neon-red" : "text-zinc-400"
                            )}>
                                <span className="opacity-50 mr-2">{new Date().toLocaleTimeString()}</span>
                                {log}
                            </div>
                        ))}
                    </div>
                </GlassCard>

                {/* Database Health */}
                <GlassCard title="Database Health" neonAccent="green" className="flex flex-col justify-around">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <Database className="w-5 h-5 text-neon-green" />
                            <span className="text-zinc-300">Disk Usage</span>
                        </div>
                        <span className="font-mono font-bold text-white">40%</span>
                    </div>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <Server className="w-5 h-5 text-neon-green" />
                            <span className="text-zinc-300">Queue Size</span>
                        </div>
                        <span className="font-mono font-bold text-white">0</span>
                    </div>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <Activity className="w-5 h-5 text-neon-green" />
                            <span className="text-zinc-300">Write Latency</span>
                        </div>
                        <span className="font-mono font-bold text-white">2ms</span>
                    </div>
                </GlassCard>
            </div>
        </div>
    );
}

function StatusBadge({ label, status, color }: { label: string; status: string; color: "green" | "amber" | "red" }) {
    return (
        <GlassCard className="flex items-center justify-between p-3 bg-white/5">
            <span className="text-xs font-bold text-zinc-400 tracking-wider">{label}</span>
            <div className={cn(
                "px-2 py-0.5 rounded text-xs font-bold border",
                color === "green" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                    color === "amber" ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
                        "bg-rose-500/10 text-rose-400 border-rose-500/20"
            )}>
                {status}
            </div>
        </GlassCard>
    );
}
