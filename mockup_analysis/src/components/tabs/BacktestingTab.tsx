import { Activity, Brain, Play, Settings, CheckCircle, AlertCircle, Loader } from 'lucide-react';
import { Button } from '../ui/button';
import { Progress } from '../ui/progress';
import { Badge } from '../ui/badge';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Switch } from '../ui/switch';
import { Slider } from '../ui/slider';
import { useState } from 'react';

export function BacktestingTab() {
  const [isRunning, setIsRunning] = useState(false);

  // Mock autonomous backtesting status
  const autonomousBacktests = [
    {
      id: 'auto-1',
      strategy: 'HMM',
      status: 'running' as const,
      progress: 67,
      startTime: Date.now() - 3600000,
      sharpe: 1.82,
      iterations: 45,
    },
    {
      id: 'auto-2',
      strategy: 'Momentum',
      status: 'completed' as const,
      progress: 100,
      startTime: Date.now() - 7200000,
      sharpe: 2.14,
      iterations: 100,
    },
    {
      id: 'auto-3',
      strategy: 'MeanRev',
      status: 'queued' as const,
      progress: 0,
      startTime: null,
      sharpe: null,
      iterations: 0,
    },
  ];

  // Mock ML status
  const mlModels = [
    {
      id: 'ml-1',
      name: 'Price Predictor v3',
      status: 'training' as const,
      accuracy: 0.847,
      epoch: 142,
      totalEpochs: 200,
      eta: '18m',
    },
    {
      id: 'ml-2',
      name: 'Volume Analyzer',
      status: 'ready' as const,
      accuracy: 0.912,
      lastTrained: Date.now() - 86400000,
    },
    {
      id: 'ml-3',
      name: 'Sentiment Model',
      status: 'error' as const,
      error: 'Training data corrupted',
    },
  ];

  return (
    <div className="p-6 space-y-6">
      {/* Autonomous Backtesting */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-zinc-300">Autonomous Backtesting</h3>
          <Button
            size="sm"
            className="gap-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-400/30"
          >
            <Play className="w-4 h-4" />
            Start New
          </Button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {autonomousBacktests.map((backtest) => (
            <BacktestCard key={backtest.id} backtest={backtest} />
          ))}
        </div>
      </div>

      {/* ML Models */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-zinc-300">ML Models</h3>
          <Button
            size="sm"
            className="gap-2 bg-violet-500/20 hover:bg-violet-500/30 text-violet-400 border border-violet-400/30"
          >
            <Brain className="w-4 h-4" />
            Train New Model
          </Button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {mlModels.map((model) => (
            <MLModelCard key={model.id} model={model} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Manual Backtesting Settings */}
        <div className="bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-4">
            <Settings className="w-5 h-5 text-cyan-400" />
            <h3 className="text-zinc-300">Manual Backtesting</h3>
          </div>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-xs text-zinc-400">Strategy</Label>
              <Select defaultValue="hmm">
                <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="hmm">HMM Trend</SelectItem>
                  <SelectItem value="momentum">Momentum</SelectItem>
                  <SelectItem value="meanrev">Mean Reversion</SelectItem>
                  <SelectItem value="breakout">Breakout</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-zinc-400">Time Period</Label>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="date"
                  defaultValue="2024-01-01"
                  className="bg-zinc-800/50 border-zinc-700 font-mono text-xs"
                />
                <Input
                  type="date"
                  defaultValue="2024-10-30"
                  className="bg-zinc-800/50 border-zinc-700 font-mono text-xs"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-zinc-400">Initial Capital ($)</Label>
              <Input
                type="number"
                defaultValue="50000"
                className="bg-zinc-800/50 border-zinc-700 font-mono"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-zinc-400">Commission (%)</Label>
              <Slider
                defaultValue={[0.1]}
                max={1}
                step={0.01}
                className="[&_[role=slider]]:bg-cyan-400 [&_[role=slider]]:border-cyan-400"
              />
              <span className="text-xs text-zinc-500 font-mono">0.10%</span>
            </div>

            <div className="flex items-center justify-between">
              <Label className="text-xs text-zinc-400">Include Slippage</Label>
              <Switch defaultChecked />
            </div>

            <Button
              className="w-full gap-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-400/30"
              onClick={() => setIsRunning(!isRunning)}
            >
              <Play className="w-4 h-4" />
              {isRunning ? 'Running...' : 'Start Backtest'}
            </Button>
          </div>
        </div>

        {/* ML Promotion Settings */}
        <div className="bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-4">
            <Brain className="w-5 h-5 text-violet-400" />
            <h3 className="text-zinc-300">ML Promotion Settings</h3>
          </div>

          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between mb-1">
                <Label className="text-xs text-zinc-400">Auto-promote Threshold</Label>
                <span className="text-xs text-zinc-500 font-mono">85%</span>
              </div>
              <Slider
                defaultValue={[85]}
                max={100}
                step={1}
                className="[&_[role=slider]]:bg-violet-400 [&_[role=slider]]:border-violet-400"
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between mb-1">
                <Label className="text-xs text-zinc-400">Min Training Epochs</Label>
                <span className="text-xs text-zinc-500 font-mono">100</span>
              </div>
              <Slider
                defaultValue={[100]}
                max={500}
                step={10}
                className="[&_[role=slider]]:bg-violet-400 [&_[role=slider]]:border-violet-400"
              />
            </div>

            <div className="flex items-center justify-between">
              <Label className="text-xs text-zinc-400">Auto Deploy to Paper</Label>
              <Switch defaultChecked />
            </div>

            <div className="flex items-center justify-between">
              <Label className="text-xs text-zinc-400">Require Manual Review</Label>
              <Switch />
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-zinc-400">Validation Strategy</Label>
              <Select defaultValue="kfold">
                <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="kfold">K-Fold Cross Validation</SelectItem>
                  <SelectItem value="timeseries">Time Series Split</SelectItem>
                  <SelectItem value="walk">Walk Forward</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-zinc-400">Model Architecture</Label>
              <Select defaultValue="lstm">
                <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="lstm">LSTM</SelectItem>
                  <SelectItem value="transformer">Transformer</SelectItem>
                  <SelectItem value="gru">GRU</SelectItem>
                  <SelectItem value="ensemble">Ensemble</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <Button
              className="w-full gap-2 bg-violet-500/20 hover:bg-violet-500/30 text-violet-400 border border-violet-400/30"
            >
              <CheckCircle className="w-4 h-4" />
              Save Settings
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function BacktestCard({ backtest }: { backtest: any }) {
  const statusConfig = {
    running: {
      icon: <Loader className="w-4 h-4 animate-spin" />,
      color: 'cyan',
      bgColor: 'bg-cyan-500/20',
      borderColor: 'border-cyan-400/30',
      textColor: 'text-cyan-400',
    },
    completed: {
      icon: <CheckCircle className="w-4 h-4" />,
      color: 'emerald',
      bgColor: 'bg-emerald-500/20',
      borderColor: 'border-emerald-400/30',
      textColor: 'text-emerald-400',
    },
    queued: {
      icon: <Activity className="w-4 h-4" />,
      color: 'zinc',
      bgColor: 'bg-zinc-800/50',
      borderColor: 'border-zinc-700/30',
      textColor: 'text-zinc-400',
    },
  };

  const config = statusConfig[backtest.status];

  return (
    <div className={`${config.bgColor} backdrop-blur-sm border ${config.borderColor} rounded-xl p-4`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-zinc-100">{backtest.strategy}</span>
        <div className={`flex items-center gap-1 ${config.textColor}`}>
          {config.icon}
          <span className="text-xs uppercase">{backtest.status}</span>
        </div>
      </div>

      {backtest.status === 'running' && (
        <>
          <Progress value={backtest.progress} className="mb-2 h-1" />
          <div className="flex items-center justify-between text-xs text-zinc-500">
            <span>{backtest.progress}% complete</span>
            <span>{backtest.iterations} iterations</span>
          </div>
          {backtest.sharpe && (
            <div className="mt-2 pt-2 border-t border-zinc-700/50">
              <span className="text-xs text-zinc-500">Current Sharpe: </span>
              <span className="text-xs text-cyan-400 font-mono">{backtest.sharpe.toFixed(2)}</span>
            </div>
          )}
        </>
      )}

      {backtest.status === 'completed' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-500">Sharpe Ratio</span>
            <span className="text-sm text-emerald-400 font-mono">{backtest.sharpe.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-500">Iterations</span>
            <span className="text-sm text-zinc-300 font-mono">{backtest.iterations}</span>
          </div>
          <Button size="sm" className="w-full mt-2">
            View Results
          </Button>
        </div>
      )}

      {backtest.status === 'queued' && (
        <div className="text-xs text-zinc-500 text-center py-4">
          Waiting to start...
        </div>
      )}
    </div>
  );
}

function MLModelCard({ model }: { model: any }) {
  const statusConfig = {
    training: {
      icon: <Loader className="w-4 h-4 animate-spin" />,
      color: 'violet',
      bgColor: 'bg-violet-500/20',
      borderColor: 'border-violet-400/30',
      textColor: 'text-violet-400',
    },
    ready: {
      icon: <CheckCircle className="w-4 h-4" />,
      color: 'emerald',
      bgColor: 'bg-emerald-500/20',
      borderColor: 'border-emerald-400/30',
      textColor: 'text-emerald-400',
    },
    error: {
      icon: <AlertCircle className="w-4 h-4" />,
      color: 'red',
      bgColor: 'bg-red-500/20',
      borderColor: 'border-red-400/30',
      textColor: 'text-red-400',
    },
  };

  const config = statusConfig[model.status];

  return (
    <div className={`${config.bgColor} backdrop-blur-sm border ${config.borderColor} rounded-xl p-4`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-zinc-100">{model.name}</span>
        <div className={`flex items-center gap-1 ${config.textColor}`}>
          {config.icon}
          <span className="text-xs uppercase">{model.status}</span>
        </div>
      </div>

      {model.status === 'training' && (
        <>
          <Progress value={(model.epoch / model.totalEpochs) * 100} className="mb-2 h-1" />
          <div className="flex items-center justify-between text-xs text-zinc-500 mb-2">
            <span>Epoch {model.epoch}/{model.totalEpochs}</span>
            <span>ETA: {model.eta}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-500">Accuracy</span>
            <span className="text-sm text-violet-400 font-mono">{(model.accuracy * 100).toFixed(1)}%</span>
          </div>
        </>
      )}

      {model.status === 'ready' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-500">Accuracy</span>
            <span className="text-sm text-emerald-400 font-mono">{(model.accuracy * 100).toFixed(1)}%</span>
          </div>
          <Button size="sm" className="w-full mt-2 gap-2">
            <Play className="w-3 h-3" />
            Deploy
          </Button>
        </div>
      )}

      {model.status === 'error' && (
        <div className="text-xs text-red-400 text-center py-2">
          {model.error}
        </div>
      )}
    </div>
  );
}
