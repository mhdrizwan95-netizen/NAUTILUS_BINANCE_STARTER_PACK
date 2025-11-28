/**
 * ML Tab - Visualize the "Brain" of the Trading System
 * 
 * Shows HMM regime probabilities, feature importance, and model status
 */
import { useState } from 'react';
import { Activity, Brain, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { useAllStrategies } from '../lib/tradingStore';
import { cn } from '../lib/utils';

interface HMMRegime {
    timestamp: number;
    probBull: number;
    probBear: number;
    probChop: number;
    regime: 'BULL' | 'BEAR' | 'CHOP';
    confidence: number;
}

interface FeatureImportance {
    name: string;
    weight: number;
    value: number;
}

export function MLTab() {
    const strategies = useAllStrategies();
    const hmmStrategy = strategies.find((s) => s.name.includes('hmm'));

    const [features] = useState<FeatureImportance[]>([
        { name: 'Return', weight: 0.35, value: 0.02 },
        { name: 'Volatility', weight: 0.25, value: 0.15 },
        { name: 'VWAP Dev', weight: 0.20, value: -0.01 },
        { name: 'Z-Score', weight: 0.15, value: 1.2 },
        { name: 'Volume Spike', weight: 0.05, value: 0.8 },
    ]);

    // Mock current regime (in production, this comes from WebSocket)
    const currentRegime: HMMRegime = {
        timestamp: Date.now(),
        probBull: hmmStrategy?.confidence || 0.45,
        probBear: 0.30,
        probChop: 0.25,
        regime: 'BULL',
        confidence: hmmStrategy?.confidence || 0.45,
    };

    const getRegimeIcon = (regime: string) => {
        switch (regime) {
            case 'BULL':
                return <TrendingUp className="h-5 w-5 cyber-positive" />;
            case 'BEAR':
                return <TrendingDown className="h-5 w-5 cyber-negative" />;
            default:
                return <Minus className="h-5 w-5 cyber-neutral" />;
        }
    };

    const getRegimeColor = (regime: string) => {
        switch (regime) {
            case 'BULL':
                return 'cyber-positive';
            case 'BEAR':
                return 'cyber-negative';
            default:
                return 'cyber-neutral';
        }
    };

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center gap-3">
                <Brain className="h-6 w-6 cyber-positive" />
                <div>
                    <h2 className="text-xl font-semibold neon-glow">ML Intelligence</h2>
                    <p className="text-sm text-cyber-text-dim">Hidden Markov Model regime detection</p>
                </div>
            </div>

            {/* Current Regime Card */}
            <div className="glass-panel p-6">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-4">Current Market Regime</h3>
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        {getRegimeIcon(currentRegime.regime)}
                        <div>
                            <div className={cn('text-3xl font-bold', getRegimeColor(currentRegime.regime))}>
                                {currentRegime.regime}
                            </div>
                            <div className="text-sm text-cyber-text-dim">
                                Confidence: {(currentRegime.confidence * 100).toFixed(1)}%
                            </div>
                        </div>
                    </div>

                    {/* Probability Bars */}
                    <div className="flex gap-6">
                        <RegimeBar label="Bull" value={currentRegime.probBull} color="cyber-positive" />
                        <RegimeBar label="Bear" value={currentRegime.probBear} color="cyber-negative" />
                        <RegimeBar label="Chop" value={currentRegime.probChop} color="cyber-neutral" />
                    </div>
                </div>
            </div>

            {/* Feature Importance */}
            <div className="glass-panel p-6">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-4">Feature Importance</h3>
                <div className="space-y-3">
                    {features.map((feature) => (
                        <div key={feature.name} className="space-y-1">
                            <div className="flex justify-between text-sm">
                                <span className="text-cyber-text">{feature.name}</span>
                                <span className="font-mono text-cyber-text-dim">
                                    {feature.value > 0 ? '+' : ''}
                                    {feature.value.toFixed(3)}
                                </span>
                            </div>
                            <div className="flex gap-2 items-center">
                                <div className="flex-1 h-2 bg-cyber-glass-bg rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-gradient-to-r from-cyber-accent to-cyan-400 transition-all"
                                        style={{ width: `${feature.weight * 100}%` }}
                                    />
                                </div>
                                <span className="text-xs font-mono text-cyber-text-dim w-12 text-right">
                                    {(feature.weight * 100).toFixed(0)}%
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Model Status */}
            <div className="glass-panel p-6">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-4">Model Status</h3>
                <div className="grid grid-cols-3 gap-4">
                    <StatusCard label="Last Training" value="2h ago" status="ok" />
                    <StatusCard label="Model Version" value="v1.2.3" status="ok" />
                    <StatusCard label="Samples" value="10,847" status="ok" />
                </div>
            </div>

            {/* Regime Timeline (Placeholder for future chart) */}
            <div className="glass-panel p-6">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-4">Regime History</h3>
                <div className="h-64 flex items-center justify-center text-cyber-text-dim">
                    <div className="text-center">
                        <Activity className="h-12 w-12 mx-auto mb-2 opacity-50" />
                        <p>Regime probability chart (coming soon)</p>
                        <p className="text-xs">Will show Bull/Bear/Chop over time</p>
                    </div>
                </div>
            </div>
        </div>
    );
}

function RegimeBar({ label, value, color }: { label: string; value: number; color: string }) {
    return (
        <div className="text-center">
            <div className="h-24 w-12 bg-cyber-glass-bg rounded-lg overflow-hidden flex flex-col-reverse">
                <div
                    className={cn('transition-all', color)}
                    style={{
                        height: `${value * 100}%`,
                        background: `linear-gradient(to top, var(--cyber-accent), transparent)`,
                    }}
                />
            </div>
            <div className="mt-2 text-xs text-cyber-text-dim">{label}</div>
            <div className={cn('text-sm font-mono font-semibold', color)}>
                {(value * 100).toFixed(0)}%
            </div>
        </div>
    );
}

function StatusCard({
    label,
    value,
    status,
}: {
    label: string;
    value: string;
    status: 'ok' | 'warn' | 'error';
}) {
    const statusColor = status === 'ok' ? 'cyber-positive' : status === 'warn' ? 'cyber-neutral' : 'cyber-negative';

    return (
        <div className="border border-cyber-glass-border rounded-lg p-4">
            <div className="text-xs text-cyber-text-dim mb-1">{label}</div>
            <div className={cn('text-lg font-semibold', statusColor)}>{value}</div>
        </div>
    );
}
