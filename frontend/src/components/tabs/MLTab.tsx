/**
 * ML Tab - "THE BRAIN" - Real-Time HMM Visualization
 * 
 * Shows real-time regime probabilities, feature importance, and canary model status
 */
import { useState, useEffect } from 'react';
import { Brain, Activity, TrendingUp, GitBranch } from 'lucide-react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { useAllStrategies } from '../../lib/tradingStore';
import { cn } from '../../lib/utils';

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
    const strategies = useAllStrategies();
    const hmmStrategy = strategies.find((s) => s.name.includes('hmm'));

    // Real-time regime probability stream (last 30 minutes)
    const [regimeHistory, setRegimeHistory] = useState<RegimeProbability[]>([]);

    // Feature importance data
    const [features, setFeatures] = useState<FeatureImportance[]>([
        { name: 'Volatility', importance: 0.35, currentValue: 0.15 },
        { name: 'Z-Score', importance: 0.28, currentValue: 1.2 },
        { name: 'Return', importance: 0.20, currentValue: 0.02 },
        { name: 'VWAP Dev', importance: 0.12, currentValue: -0.01 },
        { name: 'Volume Spike', importance: 0.05, currentValue: 0.8 },
    ]);

    // Simulated real-time data stream
    useEffect(() => {
        const interval = setInterval(() => {
            const now = Date.now();
            const newPoint: RegimeProbability = {
                timestamp: now,
                bull: 0.3 + Math.random() * 0.4,
                bear: 0.2 + Math.random() * 0.3,
                chop: 0.2 + Math.random() * 0.3,
            };

            setRegimeHistory((prev) => {
                const updated = [...prev, newPoint];
                // Keep last 30 minutes (180 points @ 10s intervals)
                return updated.slice(-180);
            });
        }, 10000); // Update every 10 seconds

        return () => clearInterval(interval);
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
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Brain className="h-8 w-8 cyber-positive" />
                    <div>
                        <h2 className="text-2xl font-bold neon-glow cyber-positive">THE BRAIN</h2>
                        <p className="text-sm cyber-text-dim">HMM Model Intelligence Core</p>
                    </div>
                </div>

                {/* Canary Status */}
                <div className="glass px-6 py-3">
                    <div className="flex items-center gap-3">
                        <GitBranch className="h-5 w-5 neon-blue" />
                        <div>
                            <div className="text-xs cyber-text-dim">Production Model</div>
                            <div className="font-mono font-bold cyber-positive">v1.2.3</div>
                        </div>
                        <div className="w-px h-8 bg-white/10 mx-2" />
                        <div>
                            <div className="text-xs cyber-text-dim">Candidate</div>
                            <div className="font-mono font-bold neon-yellow">v1.3.0-rc1</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Current Regime Status */}
            <div className="glass p-6">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold cyber-text">Current Market Regime</h3>
                    <div className="flex items-center gap-2">
                        <Activity className="h-4 w-4 cyber-positive cyber-pulse" />
                        <span className="text-xs cyber-text-dim">Live</span>
                    </div>
                </div>

                <div className="grid grid-cols-4 gap-6">
                    <div className="col-span-1">
                        <div className={cn(
                            'text-5xl font-bold font-mono neon-glow',
                            dominantRegime === 'BULL' ? 'cyber-positive' :
                                dominantRegime === 'BEAR' ? 'cyber-negative' : 'neon-yellow'
                        )}>
                            {dominantRegime}
                        </div>
                        <div className="text-sm cyber-text-dim mt-2">
                            Confidence: {currentRegime ? (Math.max(currentRegime.bull, currentRegime.bear, currentRegime.chop) * 100).toFixed(1) : 0}%
                        </div>
                    </div>

                    {currentRegime && (
                        <>
                            <ProbabilityBar label="Bull" value={currentRegime.bull} color="cyber-positive" />
                            <ProbabilityBar label="Bear" value={currentRegime.bear} color="cyber-negative" />
                            <ProbabilityBar label="Chop" value={currentRegime.chop} color="neon-yellow" />
                        </>
                    )}
                </div>
            </div>

            {/* Regime Probability Stream (Real-Time Chart) */}
            <div className="glass p-6">
                <h3 className="text-lg font-semibold cyber-text mb-4">Regime Probability Stream (30min)</h3>
                <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={regimeHistory.map(p => ({
                        time: new Date(p.timestamp).toLocaleTimeString(),
                        Bull: (p.bull * 100).toFixed(1),
                        Bear: (p.bear * 100).toFixed(1),
                        Chop: (p.chop * 100).toFixed(1),
                    }))}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis
                            dataKey="time"
                            stroke="#b0b7bf"
                            style={{ fontSize: '12px' }}
                        />
                        <YAxis
                            stroke="#b0b7bf"
                            style={{ fontSize: '12px' }}
                            domain={[0, 100]}
                        />
                        <Tooltip
                            contentStyle={{
                                background: 'rgba(15, 15, 35, 0.95)',
                                border: '1px solid rgba(255,255,255,0.1)',
                                borderRadius: '8px'
                            }}
                        />
                        <Legend />
                        <Line
                            type="monotone"
                            dataKey="Bull"
                            stroke="#00ff9d"
                            strokeWidth={2}
                            dot={false}
                        />
                        <Line
                            type="monotone"
                            dataKey="Bear"
                            stroke="#ff6b6b"
                            strokeWidth={2}
                            dot={false}
                        />
                        <Line
                            type="monotone"
                            dataKey="Chop"
                            stroke="#ffd93d"
                            strokeWidth={2}
                            dot={false}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            {/* Feature Importance Bar Chart */}
            <div className="glass p-6">
                <h3 className="text-lg font-semibold cyber-text mb-4">Feature Importance (Decision Drivers)</h3>
                <ResponsiveContainer width="100%" height={250}>
                    <BarChart
                        data={features}
                        layout="vertical"
                        margin={{ left: 80 }}
                    >
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis
                            type="number"
                            domain={[0, 1]}
                            stroke="#b0b7bf"
                            style={{ fontSize: '12px' }}
                        />
                        <YAxis
                            type="category"
                            dataKey="name"
                            stroke="#b0b7bf"
                            style={{ fontSize: '12px' }}
                        />
                        <Tooltip
                            contentStyle={{
                                background: 'rgba(15, 15, 35, 0.95)',
                                border: '1px solid rgba(255,255,255,0.1)',
                                borderRadius: '8px'
                            }}
                            formatter={(value: any) => (value * 100).toFixed(1) + '%'}
                        />
                        <Bar
                            dataKey="importance"
                            fill="url(#colorGradient)"
                            radius={[0, 8, 8, 0]}
                        />
                        <defs>
                            <linearGradient id="colorGradient" x1="0" y1="0" x2="1" y2="0">
                                <stop offset="0%" stopColor="#00ff9d" stopOpacity={0.8} />
                                <stop offset="100%" stopColor="#00d3ff" stopOpacity={0.8} />
                            </linearGradient>
                        </defs>
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}

function ProbabilityBar({ label, value, color }: { label: string; value: number; color: string }) {
    return (
        <div>
            <div className="flex justify-between items-center mb-2">
                <span className="text-sm cyber-text-dim">{label}</span>
                <span className={cn('text-lg font-mono font-bold', color)}>
                    {(value * 100).toFixed(1)}%
                </span>
            </div>
            <div className="h-4 bg-white/5 rounded-full overflow-hidden">
                <div
                    className={cn('h-full transition-all duration-500', color)}
                    style={{
                        width: `${value * 100}%`,
                        background: `linear-gradient(90deg, currentColor, transparent)`
                    }}
                />
            </div>
        </div>
    );
}
