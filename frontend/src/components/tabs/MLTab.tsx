/**
 * ML Tab - "THE NEURAL LINK" - DeepSeek & HMM Antigravity Stream
 * 
 * Shows real-time AI reasoning, regime probabilities, and neural feature streams.
 */
import { Brain, Activity, Layers, MessageSquare, Terminal } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { SVGProps } from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area } from 'recharts';

import { useAllStrategies } from '../../lib/tradingStore';
import type { StrategyStatus } from '../../lib/tradingStore';
import { getMetricsModels } from '../../lib/api';
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

interface HMMRegime {
    timestamp: number;
    probBull: number;
    probBear: number;
    probChop: number;
    regime: 'BULL' | 'BEAR' | 'CHOP' | 'UNKNOWN';
    confidence: number;
}

interface FeatureHistory {
    timestamp: number;
    vol: number;
    ret: number;
    dev_vwap: number;
    zscore: number;
    vol_spike: number;
}

function parseModelDate(dateStr: string): string {
    // Expects "YYYYMMDD_HHMMSS"
    if (!dateStr || dateStr.length < 15) return "—";
    const y = dateStr.substring(0, 4);
    const m = dateStr.substring(4, 6);
    const d = dateStr.substring(6, 8);
    const H = dateStr.substring(9, 11);
    const M = dateStr.substring(11, 13);
    return `${y}-${m}-${d} ${H}:${M}`;
}

export function MLTab() {
    // Fetch Model History
    const { data: modelsData } = useQuery({
        queryKey: ['metrics', 'models'],
        queryFn: () => getMetricsModels({ limit: 1 }),
        refetchInterval: 30000,
    });

    const latestModel = modelsData?.data?.[0];
    const modelVersion = latestModel?.version_id || "—";
    const lastTrained = latestModel?.created_at ? parseModelDate(latestModel.created_at) : "—";
    const accuracy = latestModel?.metrics?.metric_value
        ? `${(latestModel.metrics.metric_value * 100).toFixed(1)}%`
        : "—";

    // Real-time regime probability stream (last 30 minutes)
    const [regimeHistory, setRegimeHistory] = useState<RegimeProbability[]>([]);
    // Real-time feature history stream
    const [featureHistory, setFeatureHistory] = useState<FeatureHistory[]>([]);

    // Refs to hold latest data for the interval loop
    const latestRegime = useRef<HMMRegime | null>(null);
    const latestStrategy = useRef<StrategyStatus | undefined>(undefined);

    const strategies = useAllStrategies();

    // Priority: DeepSeek -> HMM -> Ensemble -> Any Active
    const deepseekParams = strategies.find(s => s.name.toLowerCase().includes('deepseek'));
    const hmmParams = strategies.find(s => s.name.toLowerCase().includes('hmm'));

    const activeStrategy = deepseekParams || hmmParams
        || strategies.find((s) => s.name.toLowerCase().includes('ensemble'))
        || strategies.find(s => s.enabled);

    // DeepSeek Specifics
    const isDeepSeek = activeStrategy?.name.toLowerCase().includes('deepseek');
    const reasoning = activeStrategy?.metrics?.reasoning || null;
    const modelName = activeStrategy?.metrics?.model || "Standard HMM";

    // Real-time feature state
    const [features, setFeatures] = useState<FeatureImportance[]>([
        { name: 'Vol Raw', importance: 0.35, currentValue: 0 },
        { name: 'Returns', importance: 0.25, currentValue: 0 },
        { name: 'VWAP Dist', importance: 0.20, currentValue: 0 },
        { name: 'Z-Score', importance: 0.15, currentValue: 0 },
        { name: 'Vol Spike', importance: 0.05, currentValue: 0 },
    ]);

    // Real-time synchronization with active strategy state
    useEffect(() => {
        if (activeStrategy?.metrics?.features) {
            const f = activeStrategy.metrics.features;
            // Map backend keys to UI labels
            // Backend: ret, vol, dev_vwap, zscore, vol_spike
            setFeatures([
                { name: 'Vol Raw', importance: 0.35, currentValue: f.vol || 0 },
                { name: 'Returns', importance: 0.25, currentValue: f.ret || 0 },
                { name: 'VWAP Dist', importance: 0.20, currentValue: f.dev_vwap || 0 },
                { name: 'Z-Score', importance: 0.15, currentValue: f.zscore || 0 },
                { name: 'Vol Spike', importance: 0.05, currentValue: f.vol_spike || 0 },
            ].sort((a, b) => Math.abs(b.currentValue) - Math.abs(a.currentValue)));
        }
    }, [activeStrategy]);

    // Derived from real strategy state or default to "SCANNING"
    const currentRegime: HMMRegime = activeStrategy ? {
        timestamp: Date.now(),
        // Map simple signal (-1 to 1) to Probabilities
        // If metrics are present, use them for more accurate probabilities if available, otherwise heuristic
        probBull: activeStrategy.metrics?.p_bull || (activeStrategy.kind === 'HMM' ? (activeStrategy as any).signal > 0 : 0.33),
        probBear: 0.1,
        probChop: 0.1,
        regime: 'UNKNOWN',
        confidence: activeStrategy.performance?.sharpe || 0, // Using strategy standard field if available
    } : {
        timestamp: Date.now(),
        probBull: 0.33,
        probBear: 0.33,
        probChop: 0.34,
        regime: 'UNKNOWN',
        confidence: 0,
    };

    // Re-implementing the mapping logic from previous file correctly
    const computedRegime: HMMRegime = activeStrategy ? {
        timestamp: Date.now(),
        // Map simple signal (-1 to 1) to Probabilities
        probBull: (activeStrategy.signal ?? 0) > 0.05 ? (0.5 + (activeStrategy.confidence || 0) / 2) : 0.1,
        probBear: (activeStrategy.signal ?? 0) < -0.05 ? (0.5 + (activeStrategy.confidence || 0) / 2) : 0.1,
        probChop: Math.abs(activeStrategy.signal ?? 0) <= 0.05 ? (0.5 + (activeStrategy.confidence || 0) / 2) : 0.1,
        regime: (activeStrategy.signal ?? 0) > 0.05 ? 'BULL' : (activeStrategy.signal ?? 0) < -0.05 ? 'BEAR' : 'CHOP',
        confidence: activeStrategy.confidence || 0,
    } : currentRegime;

    // Use computedRegime for consistency with old behavior
    const dominantRegime = computedRegime.regime === 'UNKNOWN' ? 'UNKNOWN' : computedRegime.regime;

    // Sync refs
    useEffect(() => {
        latestRegime.current = computedRegime;
        latestStrategy.current = activeStrategy;
    }, [computedRegime, activeStrategy]);

    // Real-time data stream for regime and feature history (Decoupled Timer)
    useEffect(() => {
        const interval = setInterval(() => {
            const now = Date.now();
            const regime = latestRegime.current;
            const strat = latestStrategy.current;

            if (regime) {
                // Update Regime History
                setRegimeHistory(prev => {
                    const newPoint = {
                        timestamp: now,
                        bull: regime.probBull,
                        bear: regime.probBear,
                        chop: regime.probChop
                    };
                    return [...prev.slice(-1800), newPoint];
                });
            }

            if (strat) {
                // Update Feature History
                setFeatureHistory(prev => {
                    const f = strat?.metrics?.features || {};
                    const newPoint = {
                        timestamp: now,
                        vol: f.vol || 0,
                        ret: f.ret || 0,
                        dev_vwap: f.dev_vwap || 0,
                        zscore: f.zscore || 0,
                        vol_spike: f.vol_spike || 0,
                    };
                    return [...prev.slice(-1800), newPoint];
                });
            }

        }, 1000);
        return () => clearInterval(interval);
    }, []); // Empty dependency array ensures timer is stable

    return (
        <div className="p-8 space-y-8 min-h-screen flex flex-col max-w-[1920px] mx-auto w-full bg-deep-space text-zinc-100 font-header pb-20">

            {/* HEADER: Model Status */}
            <div className="grid grid-cols-4 gap-6 shrink-0">
                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Brain className="h-8 w-8 text-neon-cyan" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Active Brain</div>
                        <div className="text-xl font-data font-bold text-white truncate max-w-[150px]">{activeStrategy?.name || "None"}</div>
                    </div>
                </GlassCard>

                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Terminal className="h-8 w-8 text-neon-amber" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Model Type</div>
                        <div className="text-xl font-data font-bold text-white truncate max-w-[150px]">{modelName}</div>
                    </div>
                </GlassCard>

                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Activity className="h-8 w-8 text-neon-green" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Confidence</div>
                        <div className="text-xl font-data font-bold text-neon-green">{((activeStrategy?.confidence || 0) * 100).toFixed(1)}%</div>
                    </div>
                </GlassCard>

                <GlassCard className="flex items-center gap-4 p-6 bg-white/5">
                    <Layers className="h-8 w-8 text-neon-blue" />
                    <div>
                        <div className="text-xs text-zinc-400 uppercase tracking-wider">Current Signal</div>
                        <div className={cn(
                            "text-xl font-data font-bold",
                            dominantRegime === 'BULL' ? "text-neon-green" :
                                dominantRegime === 'BEAR' ? "text-neon-red" :
                                    dominantRegime === 'UNKNOWN' ? "text-neon-cyan animate-pulse" : "text-neon-amber"
                        )}>
                            {dominantRegime === 'UNKNOWN' ? 'SCANNING...' : dominantRegime}
                        </div>
                    </div>
                </GlassCard>
            </div>

            {/* DEEPSEEK REASONING (If Available) */}
            {isDeepSeek && reasoning && (
                <GlassCard title="Antigravity Reasoning (DeepSeek V2)" neonAccent="purple" className="flex flex-col relative overflow-hidden group">
                    <div className="absolute top-4 right-4 animate-pulse">
                        <Brain className="w-5 h-5 text-neon-purple opacity-80" />
                    </div>
                    <div className="p-4 font-mono text-sm leading-relaxed text-zinc-300 whitespace-pre-wrap max-h-[300px] overflow-y-auto custom-scrollbar">
                        {reasoning}
                    </div>
                </GlassCard>
            )}

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
                <GlassCard title="HMM Feature Importance" neonAccent="blue" className="col-span-4 flex flex-col">
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

            {/* BOTTOM ROW: Neural Activity Monitor */}
            <div className="grid grid-cols-1 gap-8 h-[400px]">
                <GlassCard title="Neural Activity Monitor (Real-Time Feature Stream)" neonAccent="blue" className="flex flex-col">
                    <div className="flex-1 w-full h-full min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={featureHistory}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                                <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).toLocaleTimeString()} stroke="#52525b" fontSize={12} />
                                <YAxis stroke="#52525b" fontSize={12} domain={['auto', 'auto']} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', color: '#f4f4f5' }}
                                    labelFormatter={(t) => new Date(t).toLocaleTimeString()}
                                />
                                <Legend />
                                <Line type="monotone" dataKey="vol" stroke="#00d2ff" strokeWidth={2} dot={false} name="Volatility" animationDuration={0} />
                                <Line type="monotone" dataKey="zscore" stroke="#d946ef" strokeWidth={2} dot={false} name="Z-Score" animationDuration={0} />
                                <Line type="monotone" dataKey="dev_vwap" stroke="#f59e0b" strokeWidth={2} dot={false} name="VWAP Dist" animationDuration={0} />
                                <Line type="monotone" dataKey="ret" stroke="#10b981" strokeWidth={1} dot={false} name="Returns" opacity={0.5} animationDuration={0} />
                                <Line type="monotone" dataKey="vol_spike" stroke="#ef4444" strokeWidth={1} dot={false} name="Vol Spike" opacity={0.5} animationDuration={0} />
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
