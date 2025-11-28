```
/**
 * Strategy Control Panel - The Control Room
 * 
 * Dynamic strategy management, hot-swap, and emergency controls
 */
import { useState } from 'react';
import { AlertTriangle, Power, RefreshCw, Zap, Settings } from 'lucide-react';
import { useAllStrategies } from '../lib/tradingStore';
import { cn } from '../lib/utils';
import { Button } from './ui/button';
import { Switch } from './ui/switch';

interface StrategyConfig {
    [key: string]: string | number | boolean;
}

export function StrategyControlPanel() {
    const strategies = useAllStrategies();
    const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
    const [showFlattenConfirm, setShowFlattenConfirm] = useState(false);

    const handleHotSwap = async (strategyName: string) => {
        // In production: POST to /api/strategy/promote
        console.log(`Hot - swapping strategy: ${ strategyName } `);
        alert(`Hot - swap initiated for ${ strategyName }`);
    };

    const handleFlattenAll = async () => {
        // In production: POST to /api/control/flatten
        console.log('FLATTEN ALL initiated');
        alert('EMERGENCY FLATTEN: Closing all positions');
        setShowFlattenConfirm(false);
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
                        onHotSwap={() => handleHotSwap(strategy.name)}
                        onSelect={() => setSelectedStrategy(strategy.name)}
                        isSelected={selectedStrategy === strategy.name}
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

function StrategyCard({
    strategy,
    onHotSwap,
    onSelect,
    isSelected,
}: {
    strategy: any;
    onHotSwap: () => void;
    onSelect: () => void;
    isSelected: boolean;
}) {
    return (
        <div
            className={cn(
                'glass-panel p-4 cursor-pointer transition-all',
                isSelected && 'border-2 border-cyber-accent'
            )}
            onClick={onSelect}
        >
            <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                    <h4 className="font-semibold text-cyber-text">{strategy.name}</h4>
                    <div className="flex items-center gap-2 mt-1">
                        <Switch checked={strategy.enabled} />
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

function DynamicConfigForm({ strategyName }: { strategyName: string }) {
    // Mock config - in production, fetch from API based on strategy
    const [config, setConfig] = useState<StrategyConfig>({
        quote_usdt: 100,
        cooldown_sec: 30,
        confidence_threshold: 0.6,
        enabled: true,
    });

    const handleSubmit = async () => {
        // In production: POST to /api/strategy/{name}/config
        console.log(`Updating config for ${ strategyName }: `, config);
        alert(`Configuration updated for ${ strategyName }`);
    };

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
