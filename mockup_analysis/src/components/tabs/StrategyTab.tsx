import { Settings, Power, TrendingUp, Target, Zap, Activity } from 'lucide-react';
import { Switch } from '../ui/switch';
import { Button } from '../ui/button';
import { Slider } from '../ui/slider';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '../ui/accordion';
import { Badge } from '../ui/badge';
import type { Strategy, StrategyPerformance, Trade } from '../../types/trading';
import { useState } from 'react';

interface StrategyTabProps {
  strategies: Strategy[];
  performances: StrategyPerformance[];
  recentTrades: Trade[];
  onStrategyToggle?: (strategyId: string, enabled: boolean) => void;
}

export function StrategyTab({ strategies, performances, recentTrades, onStrategyToggle }: StrategyTabProps) {
  const [expandedStrategy, setExpandedStrategy] = useState<string | undefined>(undefined);

  const getStrategyMetrics = (strategyId: string) => {
    const strategyPerfs = performances.filter(p => p.strategyId === strategyId);
    const totalPnL = strategyPerfs.reduce((sum, p) => sum + p.metrics.pnl, 0);
    const avgSharpe = strategyPerfs.reduce((sum, p) => sum + p.metrics.sharpe, 0) / strategyPerfs.length || 0;
    const avgWinRate = strategyPerfs.reduce((sum, p) => sum + p.metrics.winRate, 0) / strategyPerfs.length || 0;
    const totalTrades = strategyPerfs.reduce((sum, p) => sum + p.metrics.tradeCount, 0);
    const maxDrawdown = Math.max(...strategyPerfs.map(p => p.metrics.drawdown));
    
    return { totalPnL, avgSharpe, avgWinRate, totalTrades, maxDrawdown };
  };

  const getStrategyTrades = (strategyId: string) => {
    return recentTrades.filter(trade => trade.strategyId === strategyId).slice(0, 10);
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {strategies.map((strategy) => {
          const metrics = getStrategyMetrics(strategy.id);
          
          return (
            <div
              key={strategy.id}
              className="bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl overflow-hidden"
            >
              {/* Strategy Header */}
              <div className="p-4 border-b border-zinc-800/50">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      strategy.enabled 
                        ? 'bg-cyan-500/20 text-cyan-400' 
                        : 'bg-zinc-800/50 text-zinc-600'
                    }`}>
                      <Zap className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="text-zinc-100">{strategy.name}</h3>
                      <p className="text-xs text-zinc-500 font-mono">
                        Capital: ${strategy.capital.toLocaleString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-zinc-500">
                      {strategy.enabled ? 'ACTIVE' : 'PAUSED'}
                    </span>
                    <Switch
                      checked={strategy.enabled}
                      onCheckedChange={(checked) => onStrategyToggle?.(strategy.id, checked)}
                    />
                  </div>
                </div>

                {/* Quick Metrics */}
                <div className="grid grid-cols-4 gap-2">
                  <div className="text-center">
                    <p className="text-xs text-zinc-500">PnL</p>
                    <p className={`font-mono text-sm ${metrics.totalPnL >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {metrics.totalPnL >= 0 ? '+' : ''}{(metrics.totalPnL / 1000).toFixed(1)}k
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-zinc-500">Sharpe</p>
                    <p className="font-mono text-sm text-cyan-400">
                      {metrics.avgSharpe.toFixed(2)}
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-zinc-500">Win Rate</p>
                    <p className="font-mono text-sm text-zinc-300">
                      {(metrics.avgWinRate * 100).toFixed(0)}%
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-zinc-500">Trades</p>
                    <p className="font-mono text-sm text-zinc-300">
                      {metrics.totalTrades}
                    </p>
                  </div>
                </div>
              </div>

              {/* Strategy Configuration & Recent Trades */}
              <Accordion type="single" collapsible value={expandedStrategy} onValueChange={setExpandedStrategy}>
                <AccordionItem value={`${strategy.id}-params`} className="border-none">
                  <AccordionTrigger className="px-4 py-3 hover:bg-zinc-800/30 text-sm text-zinc-400">
                    <div className="flex items-center gap-2">
                      <Settings className="w-4 h-4" />
                      <span>Strategy Parameters</span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="px-4 pb-4">
                    <StrategyParameters strategyName={strategy.name} />
                  </AccordionContent>
                </AccordionItem>

                <AccordionItem value={`${strategy.id}-trades`} className="border-none">
                  <AccordionTrigger className="px-4 py-3 hover:bg-zinc-800/30 text-sm text-zinc-400">
                    <div className="flex items-center gap-2">
                      <Activity className="w-4 h-4" />
                      <span>Recent Trades ({getStrategyTrades(strategy.id).length})</span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="px-4 pb-4">
                    <div className="space-y-2">
                      {getStrategyTrades(strategy.id).map((trade) => (
                        <div
                          key={trade.id}
                          className="flex items-center justify-between p-2 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <Badge 
                              variant={trade.side === 'buy' ? 'default' : 'secondary'}
                              className={`text-xs ${
                                trade.side === 'buy' 
                                  ? 'bg-emerald-500/20 text-emerald-400 border-emerald-400/30' 
                                  : 'bg-red-500/20 text-red-400 border-red-400/30'
                              }`}
                            >
                              {trade.side.toUpperCase()}
                            </Badge>
                            <span className="text-xs text-zinc-300 font-mono">{trade.symbol}</span>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-zinc-500 font-mono">
                              {trade.quantity.toFixed(4)}
                            </span>
                            <span className="text-xs text-zinc-400 font-mono">
                              {formatCurrency(trade.price)}
                            </span>
                            {trade.pnl !== undefined && (
                              <span className={`text-xs font-mono ${
                                trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                              }`}>
                                {trade.pnl >= 0 ? '+' : ''}{formatCurrency(trade.pnl)}
                              </span>
                            )}
                            <span className="text-xs text-zinc-600 font-mono">
                              {formatTime(trade.timestamp)}
                            </span>
                          </div>
                        </div>
                      ))}
                      {getStrategyTrades(strategy.id).length === 0 && (
                        <p className="text-xs text-zinc-600 text-center py-4">No recent trades</p>
                      )}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>

              {/* Markets */}
              <div className="px-4 pb-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-zinc-500">Markets:</span>
                  {strategy.markets.map((market) => (
                    <span
                      key={market}
                      className="text-xs px-2 py-1 rounded-md bg-zinc-800/50 text-zinc-400"
                    >
                      {market}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StrategyParameters({ strategyName }: { strategyName: string }) {
  // Mock parameters based on strategy type
  const getParameters = () => {
    switch (strategyName) {
      case 'HMM':
        return (
          <div className="space-y-4">
            <SliderParameter label="Hidden States" value={[5]} max={10} step={1} />
            <SliderParameter label="Observation Window" value={[20]} max={100} step={5} />
            <SliderParameter label="Confidence Threshold" value={[0.75]} max={1} step={0.05} />
          </div>
        );
      case 'Scalp':
        return (
          <div className="space-y-4">
            <SliderParameter label="Spread %" value={[0.2]} max={2} step={0.1} />
            <SliderParameter label="Stop Loss %" value={[0.5]} max={5} step={0.1} />
            <SelectParameter label="Order Type" value="limit" options={['limit', 'market', 'post-only']} />
            <InputParameter label="Max Scalps/Day" value="100" type="number" />
          </div>
        );
      case 'Momentum':
        return (
          <div className="space-y-4">
            <SliderParameter label="Surge Threshold %" value={[5]} max={20} step={1} />
            <SliderParameter label="Trailing Stop %" value={[8]} max={20} step={1} />
            <SliderParameter label="Lookback Minutes" value={[60]} max={240} step={15} />
          </div>
        );
      default:
        return (
          <div className="space-y-4">
            <SliderParameter label="Risk Factor" value={[0.5]} max={1} step={0.1} />
            <SliderParameter label="Position Size %" value={[2]} max={10} step={0.5} />
            <InputParameter label="Max Positions" value="5" type="number" />
          </div>
        );
    }
  };

  return <div className="space-y-4">{getParameters()}</div>;
}

function SliderParameter({ label, value, max, step }: { label: string; value: number[]; max: number; step: number }) {
  const [localValue, setLocalValue] = useState(value);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-zinc-400">{label}</Label>
        <span className="text-xs font-mono text-zinc-300">{localValue[0].toFixed(step < 1 ? 2 : 0)}</span>
      </div>
      <Slider
        value={localValue}
        onValueChange={setLocalValue}
        max={max}
        step={step}
        className="[&_[role=slider]]:bg-cyan-400 [&_[role=slider]]:border-cyan-400"
      />
    </div>
  );
}

function SelectParameter({ label, value, options }: { label: string; value: string; options: string[] }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-zinc-400">{label}</Label>
      <Select defaultValue={value}>
        <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function InputParameter({ label, value, type }: { label: string; value: string; type: string }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-zinc-400">{label}</Label>
      <Input
        type={type}
        defaultValue={value}
        className="bg-zinc-800/50 border-zinc-700 font-mono"
      />
    </div>
  );
}
