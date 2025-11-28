/**
 * Backtesting Comparison - Compare multiple backtest runs
 * 
 * Overlay equity curves and drill down into specific trades
 */
import { useState } from 'react';
import { TrendingUp } from 'lucide-react';
import { cn } from '../lib/utils';

interface BacktestRun {
    id: string;
    name: string;
    startDate: string;
    endDate: string;
    finalEquity: number;
    sharpe: number;
    maxDrawdown: number;
    winRate: number;
    color: string;
}

export function BacktestingComparison() {
    const [selectedRuns, setSelectedRuns] = useState<string[]>(['run1', 'run2']);

    // Mock backtest runs
    const backtests: BacktestRun[] = [
        {
            id: 'run1',
            name: 'HMM v1.2 (Conservative)',
            startDate: '2024-01-01',
            endDate: '2024-11-28',
            finalEquity: 12450,
            sharpe: 1.8,
            maxDrawdown: 0.12,
            winRate: 0.58,
            color: '#00ff9d',
        },
        {
            id: 'run2',
            name: 'HMM v1.2 (Aggressive)',
            startDate: '2024-01-01',
            endDate: '2024-11-28',
            finalEquity: 15200,
            sharpe: 1.5,
            maxDrawdown: 0.22,
            winRate: 0.54,
            color: '#00b4d8',
        },
        {
            id: 'run3',
            name: 'Momentum Breakout',
            startDate: '2024-01-01',
            endDate: '2024-11-28',
            finalEquity: 11800,
            sharpe: 1.6,
            maxDrawdown: 0.15,
            winRate: 0.52,
            color: '#ffd93d',
        },
    ];

    const toggleRun = (id: string) => {
        setSelectedRuns((prev) =>
            prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]
        );
    };

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center gap-3">
                <TrendingUp className="h-6 w-6 cyber-positive" />
                <div>
                    <h2 className="text-xl font-semibold neon-glow">Backtesting Lab</h2>
                    <p className="text-sm text-cyber-text-dim">Compare strategy performance</p>
                </div>
            </div>

            {/* Run Selection */}
            <div className="glass-panel p-4">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-3">Select Runs to Compare</h3>
                <div className="space-y-2">
                    {backtests.map((run) => (
                        <label
                            key={run.id}
                            className={cn(
                                'flex items-center gap-3 p-3 rounded cursor-pointer transition-all',
                                selectedRuns.includes(run.id)
                                    ? 'bg-cyber-glass-bg border border-cyber-glass-border'
                                    : 'hover:bg-cyber-glass-bg/50'
                            )}
                        >
                            <input
                                type="checkbox"
                                checked={selectedRuns.includes(run.id)}
                                onChange={() => toggleRun(run.id)}
                                className="w-4 h-4"
                            />
                            <div
                                className="w-3 h-3 rounded-full"
                                style={{ backgroundColor: run.color }}
                            />
                            <div className="flex-1">
                                <div className="text-sm font-medium text-cyber-text">{run.name}</div>
                                <div className="text-xs text-cyber-text-dim">
                                    {run.startDate} → {run.endDate}
                                </div>
                            </div>
                            <div className="text-right">
                                <div className={cn('text-sm font-semibold', run.finalEquity > 10000 ? 'cyber-positive' : 'cyber-negative')}>
                                    ${run.finalEquity.toLocaleString()}
                                </div>
                                <div className="text-xs text-cyber-text-dim">
                                    Sharpe {run.sharpe.toFixed(2)}
                                </div>
                            </div>
                        </label>
                    ))}
                </div>
            </div>

            {/* Comparison Chart Placeholder */}
            <div className="glass-panel p-6">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-4">Equity Curve Overlay</h3>
                <div className="h-64 flex items-center justify-center border border-cyber-glass-border rounded">
                    <div className="text-center text-cyber-text-dim">
                        <TrendingUp className="h-12 w-12 mx-auto mb-2 opacity-50" />
                        <p>Equity curve chart (coming soon)</p>
                        <p className="text-xs">Will overlay selected backtest runs</p>
                    </div>
                </div>
            </div>

            {/* Metrics Comparison */}
            <div className="glass-panel p-6">
                <h3 className="text-sm font-medium text-cyber-text-dim mb-4">Metrics Comparison</h3>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-cyber-glass-border">
                                <th className="text-left py-2 text-cyber-text-dim font-normal">Metric</th>
                                {backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((run) => (
                                        <th key={run.id} className="text-right py-2 text-cyber-text-dim font-normal">
                                            {run.name}
                                        </th>
                                    ))}
                            </tr>
                        </thead>
                        <tbody className="font-mono">
                            <MetricRow
                                label="Final Equity"
                                values={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => `$${b.finalEquity.toLocaleString()}`)}
                                colors={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => (b.finalEquity > 10000 ? 'cyber-positive' : 'cyber-negative'))}
                            />
                            <MetricRow
                                label="Sharpe Ratio"
                                values={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => b.sharpe.toFixed(2))}
                                colors={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => (b.sharpe > 1.5 ? 'cyber-positive' : 'cyber-neutral'))}
                            />
                            <MetricRow
                                label="Max Drawdown"
                                values={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => `${(b.maxDrawdown * 100).toFixed(1)}%`)}
                                colors={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => (b.maxDrawdown < 0.15 ? 'cyber-positive' : 'cyber-negative'))}
                            />
                            <MetricRow
                                label="Win Rate"
                                values={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => `${(b.winRate * 100).toFixed(1)}%`)}
                                colors={backtests
                                    .filter((b) => selectedRuns.includes(b.id))
                                    .map((b) => (b.winRate > 0.55 ? 'cyber-positive' : 'cyber-neutral'))}
                            />
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

function MetricRow({ label, values, colors }: { label: string; values: string[]; colors: string[] }) {
    return (
        <tr className="border-b border-cyber-glass-border/30">
            <td className="py-3 text-cyber-text-dim">{label}</td>
            {values.map((value, i) => (
                <td key={i} className={cn('py-3 text-right', colors[i])}>
                    {value}
                </td>
            ))}
        </tr>
    );
}
