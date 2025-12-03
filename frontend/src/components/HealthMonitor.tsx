/**
 * Health Monitor Component - "SYSTEM INTERNALS"
 * 
 * Engineering view: Latency, Docker health, and API limits.
 */
import { Activity, Cpu, HardDrive, Server, Database } from 'lucide-react';
import { useEffect, useState } from 'react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';

import { cn } from '../lib/utils';
import { GlassCard } from './ui/GlassCard';

export function HealthMonitor() {
    // Simulated Health State
    const [heartbeatHistory, setHeartbeatHistory] = useState<{ i: number; v: number }[]>([]);
    const [latencyMap, setLatencyMap] = useState<number[]>(Array(50).fill(0));
    const [logs, setLogs] = useState<string[]>([]);
    const [apiWeight, setApiWeight] = useState(450);

    // Simulation Loop
    useEffect(() => {
        // Initial Logs
        setLogs([
            "[INFO] Engine initialized successfully",
            "[INFO] Connected to Binance Futures API",
            "[INFO] ML Model loaded: v2.1.0-RC3",
            "[INFO] Websocket stream active",
        ]);

        const interval = setInterval(() => {
            // Heartbeat
            setHeartbeatHistory(prev => {
                const next = [...prev, { i: Date.now(), v: 1 + Math.random() * 0.5 }];
                return next.slice(-20);
            });

            // Latency Heatmap
            setLatencyMap(prev => {
                const next = [...prev.slice(1), Math.random() * 100];
                return next;
            });

            // API Weight
            setApiWeight(prev => {
                const change = Math.floor(Math.random() * 20) - 5;
                return Math.min(1200, Math.max(0, prev + change));
            });

            // Random Logs
            if (Math.random() > 0.8) {
                const newLog = Math.random() > 0.9
                    ? `[WARN] High slippage detected on BTCUSDT: ${Math.random().toFixed(2)}%`
                    : `[INFO] Order filled: ${Math.random() > 0.5 ? 'BUY' : 'SELL'} ETHUSDT`;
                setLogs(prev => [newLog, ...prev].slice(0, 10));
            }

        }, 1000);

        return () => clearInterval(interval);
    }, []);

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
                <GlassCard title="API Weight (Binance)" neonAccent={apiWeight > 1000 ? "red" : "green"} className="flex flex-col items-center justify-center">
                    <div className="relative w-40 h-40">
                        <svg className="transform -rotate-90" width="160" height="160">
                            <circle cx="80" cy="80" r="70" stroke="rgba(255,255,255,0.05)" strokeWidth="12" fill="none" />
                            <circle
                                cx="80" cy="80" r="70"
                                stroke={apiWeight > 1000 ? "#ff6b6b" : "#00ff9d"}
                                strokeWidth="12"
                                fill="none"
                                strokeDasharray={2 * Math.PI * 70}
                                strokeDashoffset={2 * Math.PI * 70 * (1 - apiWeight / 1200)}
                                strokeLinecap="round"
                                className="transition-all duration-500"
                            />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <div className="text-3xl font-data font-bold text-white">{apiWeight}</div>
                            <div className="text-xs text-zinc-500">/ 1200</div>
                        </div>
                    </div>
                </GlassCard>

                {/* Order Latency Heatmap */}
                <GlassCard title="Order Latency Heatmap" neonAccent="blue" className="flex flex-col">
                    <div className="flex-1 grid grid-cols-10 grid-rows-5 gap-1 content-center">
                        {latencyMap.map((lat, i) => (
                            <div
                                key={i}
                                className={cn(
                                    "rounded-sm transition-colors duration-300",
                                    lat < 20 ? "bg-[#00ff9d]/20" :
                                        lat < 50 ? "bg-[#4361ee]/40" :
                                            lat < 80 ? "bg-[#ffd93d]/60" : "bg-[#ff6b6b]"
                                )}
                                title={`${lat.toFixed(0)}ms`}
                            />
                        ))}
                    </div>
                    <div className="mt-2 flex justify-between text-xs text-zinc-500 font-mono">
                        <span>Low (&lt;20ms)</span>
                        <span>High (&gt;80ms)</span>
                    </div>
                </GlassCard>

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
                        SYSTEM HEALTHY • TICK GAP &lt; 1s
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
                        {logs.map((log, i) => (
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
