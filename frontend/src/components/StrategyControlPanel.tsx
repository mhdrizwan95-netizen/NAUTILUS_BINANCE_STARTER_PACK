/**
 * Strategy Control Panel - The Control Room
 * 
 * Dynamic strategy management, hot-swap, and emergency controls
 */
import { AlertTriangle, Power, RefreshCw, Zap, Settings } from 'lucide-react';
import { useState } from 'react';

import { useAllStrategies } from '../lib/tradingStore';
import { cn } from '../lib/utils';
import { Button } from './ui/button';
import { Switch } from './ui/switch';
import { startStrategy, stopStrategy, updateStrategy, flattenPositions } from '../lib/api';

interface StrategyConfig {
    [key: string]: string | number | boolean;
}

export function StrategyControlPanel() {
    const strategies = useAllStrategies();
    const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
    const [showFlattenConfirm, setShowFlattenConfirm] = useState(false);

    const handleHotSwap = async (strategyName: string) => {
        try {
            await startStrategy(strategyName);
            // In a real app, you might want to refresh the strategy list or show a toast
            console.log(`Strategy ${strategyName} started`);
        } catch (error) {
            console.error(`Failed to start strategy ${strategyName}:`, error);
            alert(`Failed to start strategy: ${error}`);
        }
    };

    const handleFlattenAll = async () => {
        try {
            await flattenPositions({}, "emergency_button");
            console.log('FLATTEN ALL initiated');
            alert('EMERGENCY FLATTEN: Closing all positions');
        } catch (error) {
            console.error('Failed to flatten positions:', error);
            alert(`Failed to flatten positions: ${error}`);
        } finally {
            setShowFlattenConfirm(false);
        }
    };

    const handleToggleStrategy = async (strategyName: string, enabled: boolean) => {
        try {
            if (enabled) {
                await startStrategy(strategyName);
            } else {
                await stopStrategy(strategyName);
            }
        } catch (error) {
            console.error(`Failed to toggle strategy ${strategyName}:`, error);
            alert(`Failed to toggle strategy: ${error}`);
        }
    };

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Settings className="h-6 w-6 cyber-positive" />
                    <div>
                        <h2 className="text-xl font-semibold neon-glow">Control Room</h2>
                        <p className="text-sm text-cyber-text-dim">Strategy management & emergency controls</p>
                    </div>
                </div>

                {/* Emergency Flatten Button */}
                <div className="relative">
                    {!showFlattenConfirm ? (
                        <Button
                            variant="destructive"
                            size="lg"
                            onClick={() => setShowFlattenConfirm(true)}
                            className="gap-2 border-2 border-cyber-negative bg-cyber-negative/10 hover:bg-cyber-negative/20 text-cyber-negative font-bold"
                        >
                            <Power className="h-5 w-5" />
                            FLATTEN ALL
                        </Button>
                    ) : (
                        <div className="glass-panel p-4 border-2 border-cyber-negative animate-pulse">
                            <div className="text-sm font-bold text-cyber-negative mb-2 flex items-center gap-2">
                                <AlertTriangle className="h-4 w-4" />
                                CONFIRM FLATTEN?
                            </div>
                            <div className="flex gap-2">
                                <Button
                                    variant="destructive"
                                    size="sm"
                                    onClick={handleFlattenAll}
                                    className="bg-cyber-negative text-white hover:bg-red-600"
                                >
                                    YES, FLATTEN
                                </Button>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowFlattenConfirm(false)}
                                    className="border-cyber-glass-border"
                                >
                                    Cancel
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Strategy List */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {strategies.map((strategy) => (
                    <StrategyCard
                        key={strategy.name}
                        strategy={strategy}
                        onHotSwap={() => handleHotSwap(strategy.id)}
                        onSelect={() => setSelectedStrategy(strategy.id)}
                        onToggle={(enabled) => handleToggleStrategy(strategy.id, enabled)}
                        isSelected={selectedStrategy === strategy.id}
                    />
                ))}

                {strategies.length === 0 && (
                    <div className="col-span-2 glass-panel p-12 text-center">
                        <Zap className="h-12 w-12 mx-auto mb-4 text-cyber-text-dim" />
                        <p className="text-cyber-text-dim">No active strategies</p>
                    </div>
                )}
            </div>

            {/* Selected Strategy Configuration */}
            {selectedStrategy && (
                <div className="glass-panel p-6">
                    <h3 className="text-lg font-semibold mb-4 cyber-positive">
                        Configuration: {selectedStrategy}
                    </h3>
                    <DynamicConfigForm strategyName={selectedStrategy} />
                </div>
            )}
        </div>
    );
}

interface Strategy {
    id: string;
    name: string;
    enabled: boolean;
    confidence: number;
    signal: number;
}

function StrategyCard({
    strategy,
    onHotSwap,
    onSelect,
    onToggle,
    isSelected,
}: {
    strategy: Strategy;
    onHotSwap: () => void;
    onSelect: () => void;
    onToggle: (enabled: boolean) => void;
    isSelected: boolean;
}) {
    return (
        <div
            className={cn(
                'glass-panel p-4 cursor-pointer transition-all',
                isSelected && 'border-2 border-cyber-accent'
            )}
            onClick={onSelect}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    onSelect();
                }
            }}
        >
            <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                    <h4 className="font-semibold text-cyber-text">{strategy.name}</h4>
                    <div className="flex items-center gap-2 mt-1">
                        <Switch
                            checked={strategy.enabled}
                            onCheckedChange={(checked) => onToggle(checked)}
                            onClick={(e) => e.stopPropagation()}
                        />
                        <span className="text-xs text-cyber-text-dim">
                            {strategy.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    </div>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={(e) => {
                        e.stopPropagation();
                        onHotSwap();
                    }}
                    className="gap-2 border-cyber-accent text-cyber-accent hover:bg-cyber-accent/10"
                >
                    <RefreshCw className="h-3 w-3" />
                    Hot-Swap
                </Button>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                    <div className="text-xs text-cyber-text-dim">Confidence</div>
                    <div className={cn('font-mono font-semibold', strategy.confidence > 0.5 ? 'cyber-positive' : 'cyber-neutral')}>
                        {(strategy.confidence * 100).toFixed(1)}%
                    </div>
                </div>
                <div>
                    <div className="text-xs text-cyber-text-dim">Signal</div>
                    <div className={cn('font-mono font-semibold', strategy.signal > 0 ? 'cyber-positive' : strategy.signal < 0 ? 'cyber-negative' : 'cyber-neutral')}>
                        {strategy.signal > 0 ? '+' : ''}{strategy.signal.toFixed(2)}
                    </div>
                </div>
            </div>
        </div>
    );
}

import { getStrategy } from '../lib/api';

function DynamicConfigForm({ strategyName }: { strategyName: string }) {
    const [config, setConfig] = useState<StrategyConfig>({});
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        let mounted = true;
        const fetchConfig = async () => {
            setIsLoading(true);
            try {
                const summary = await getStrategy(strategyName);
                if (mounted && summary.params) {
                    // Type assertion for simple config display
                    setConfig(summary.params as unknown as StrategyConfig);
                }
            } catch (error) {
                console.error(`Failed to fetch config for ${strategyName}:`, error);
            } finally {
                if (mounted) setIsLoading(false);
            }
        };

        fetchConfig();
        return () => { mounted = false; };
    }, [strategyName]);

    const handleSubmit = async () => {
        try {
            await updateStrategy(strategyName, config);
            console.log(`Updating config for ${strategyName}:`, config);
            alert(`Configuration updated for ${strategyName}`);
        } catch (error) {
            console.error(`Failed to update config for ${strategyName}:`, error);
            alert(`Failed to update config: ${error}`);
        }
    };

    if (isLoading) {
        return <div className="text-cyber-text-dim text-sm p-4">Loading configuration...</div>;
    }

    if (Object.keys(config).length === 0) {
        return <div className="text-cyber-text-dim text-sm p-4">No configuration parameters available for this strategy.</div>;
    }

    return (
        <div className="space-y-4">
            {Object.entries(config).map(([key, value]) => (
                <div key={key} className="grid grid-cols-2 gap-4 items-center">
                    <label className="text-sm text-cyber-text capitalize">
                        {key.replace(/_/g, ' ')}
                    </label>
                    {typeof value === 'boolean' ? (
                        <Switch
                            checked={value}
                            onCheckedChange={(checked) => setConfig({ ...config, [key]: checked })}
                        />
                    ) : typeof value === 'number' ? (
                        <input
                            type="number"
                            value={value}
                            onChange={(e) => setConfig({ ...config, [key]: parseFloat(e.target.value) })}
                            className="px-3 py-2 bg-cyber-glass-bg border border-cyber-glass-border rounded text-cyber-text font-mono text-sm"
                        />
                    ) : (
                        <input
                            type="text"
                            value={value}
                            onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
                            className="px-3 py-2 bg-cyber-glass-bg border border-cyber-glass-border rounded text-cyber-text font-mono text-sm"
                        />
                    )}
                </div>
            ))}

            <Button
                onClick={handleSubmit}
                className="w-full bg-cyber-accent text-black hover:bg-green-400 font-semibold"
            >
                Apply Configuration
            </Button>
        </div>
    );
}
