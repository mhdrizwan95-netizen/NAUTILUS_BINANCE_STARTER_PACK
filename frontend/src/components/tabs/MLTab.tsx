/**
 * ML Tab - "THE NEURAL LINK" - Real-Time HMM Visualization
 * 
 * Shows real-time regime probabilities, feature importance, and canary model status
 */
import { Brain, Activity, Layers } from 'lucide-react';
import { useState, useEffect } from 'react';
import type { SVGProps } from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area } from 'recharts';

import { cn } from '../../lib/utils';
import { GlassCard } from '../ui/GlassCard';

interface RegimeProbability {
    timestamp: number;
    bull: number;
    bear: number;
    chop: number;
}

interface FeatureImportance {
    name: string;
    importance: number;
    currentValue: number;
}

export function MLTab() {
    // Real-time regime probability stream (last 30 minutes)
    const [regimeHistory, setRegimeHistory] = useState<RegimeProbability[]>([]);

    // Feature importance data
    // Feature importance data
    const [features] = useState<FeatureImportance[]>([]);

    // Simulated real-time data stream
    // Real-time data stream would go here
    useEffect(() => {
        // Placeholder for real data subscription
    }, []);

    // Current regime
    const currentRegime = regimeHistory.length > 0 ? regimeHistory[regimeHistory.length - 1] : null;
    const dominantRegime = currentRegime
        ? currentRegime.bull > currentRegime.bear && currentRegime.bull > currentRegime.chop
            ? 'BULL'
            : currentRegime.bear > currentRegime.chop
                ? 'BEAR'
                : 'CHOP'
        : 'UNKNOWN';

    return (
        <div className="p-8 space-y-8 min-h-screen flex flex-col max-w-[1920px] mx-auto w-full bg-deep-space text-zinc-100 font-header pb-20">

            {/* HEADER: Model Status */}
            <div className="grid grid-cols-4 gap-6 shrink-0">
                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Brain className="h-8 w-8 text-neon-cyan" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Model Version</div>
                        <div className="text-xl font-data font-bold text-white">—</div>
                    </div>
                </GlassCard>

                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <ClockIcon className="h-8 w-8 text-neon-amber" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Last Trained</div>
                        <div className="text-xl font-data font-bold text-white">—</div>
                    </div>
                </GlassCard>

                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Activity className="h-8 w-8 text-neon-green" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Accuracy (24h)</div>
                        <div className="text-xl font-data font-bold text-neon-green">—</div>
                    </div>
                </GlassCard>

                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Layers className="h-8 w-8 text-neon-blue" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Current Regime</div>
                        <div className={cn(
                            "text-xl font-data font-bold",
                            dominantRegime === 'BULL' ? "text-neon-green" :
                                dominantRegime === 'BEAR' ? "text-neon-red" : "text-neon-amber"
                        )}>
                            {dominantRegime}
                        </div>
                    </div>
                </GlassCard>
            </div>

            {/* MAIN ROW: Regime Stream & Features */}
            <div className="grid grid-cols-12 gap-8 h-[450px]">

                {/* Market Regime Probability Stream */}
                <GlassCard title="Market Regime Probability Stream" neonAccent="cyan" className="col-span-8 flex flex-col">
                    <div className="flex-1 w-full h-full min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={regimeHistory}>
                                <defs>
                                    <linearGradient id="colorBull" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#00ff9d" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#00ff9d" stopOpacity={0} />
                                    </linearGradient>
                                    <linearGradient id="colorBear" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#ff6b6b" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#ff6b6b" stopOpacity={0} />
                                    </linearGradient>
                                    <linearGradient id="colorChop" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#ffd93d" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#ffd93d" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                                <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).toLocaleTimeString()} stroke="#52525b" fontSize={12} />
                                <YAxis stroke="#52525b" fontSize={12} domain={[0, 1]} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', color: '#f4f4f5' }}
                                    itemStyle={{ color: '#f4f4f5' }}
                                    labelStyle={{ color: '#a1a1aa' }}
                                    labelFormatter={(t) => new Date(t).toLocaleTimeString()}
                                />
                                <Legend />
                                <Area type="monotone" dataKey="bull" stackId="1" stroke="#00ff9d" fill="url(#colorBull)" name="Bull" />
                                <Area type="monotone" dataKey="chop" stackId="1" stroke="#ffd93d" fill="url(#colorChop)" name="Chop" />
                                <Area type="monotone" dataKey="bear" stackId="1" stroke="#ff6b6b" fill="url(#colorBear)" name="Bear" />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>
                </GlassCard>

                {/* Feature Importance */}
                <GlassCard title="Feature Importance" neonAccent="blue" className="col-span-4 flex flex-col">
                    <div className="flex-1 w-full h-full min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={features} layout="vertical" margin={{ left: 40 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                                <XAxis type="number" domain={[0, 0.5]} stroke="#52525b" fontSize={12} />
                                <YAxis dataKey="name" type="category" stroke="#52525b" fontSize={12} width={80} />
                                <Tooltip
                                    cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                                    contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', color: '#f4f4f5' }}
                                />
                                <Bar dataKey="importance" fill="#4361ee" radius={[0, 4, 4, 0]} barSize={20} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </GlassCard>
            </div>

            {/* BOTTOM ROW: Canary Model Comparison */}
            <div className="grid grid-cols-1 gap-8 h-[400px]">
                <GlassCard title="Canary Model Performance vs Production" neonAccent="amber" className="flex flex-col">
                    <div className="flex-1 w-full h-full min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={regimeHistory}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                                <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).toLocaleTimeString()} stroke="#52525b" fontSize={12} />
                                <YAxis stroke="#52525b" fontSize={12} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', color: '#f4f4f5' }}
                                    labelFormatter={(t) => new Date(t).toLocaleTimeString()}
                                />
                                <Legend />
                                <Line type="monotone" dataKey="bull" stroke="#00ff9d" strokeWidth={2} dot={false} name="Prod v2.1 (PnL)" />
                                <Line type="monotone" dataKey="chop" stroke="#ffd93d" strokeWidth={2} strokeDasharray="5 5" dot={false} name="Canary v2.2 (Shadow)" />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </GlassCard>
            </div>
        </div>
    );
}

function ClockIcon(props: SVGProps<SVGSVGElement>) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
        </svg>
    );
}
