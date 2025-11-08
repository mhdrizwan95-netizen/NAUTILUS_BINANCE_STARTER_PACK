import { Settings, Shield, TrendingUp, Zap, TrendingDown, Rocket, DollarSign, Activity } from 'lucide-react';

import { Button } from './ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Separator } from './ui/separator';
import { Slider } from './ui/slider';
import { Switch } from './ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import type {
  GlobalSettings,
  TrendStrategyConfig,
  ScalpStrategyConfig,
  MomentumStrategyConfig,
  MemeStrategyConfig,
  ListingStrategyConfig,
  VolScannerConfig,
} from '../types/settings';

interface SettingsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  globalSettings: GlobalSettings;
  onGlobalSettingsChange: (settings: GlobalSettings) => void;
  trendConfig: TrendStrategyConfig;
  scalpConfig: ScalpStrategyConfig;
  momentumConfig: MomentumStrategyConfig;
  memeConfig: MemeStrategyConfig;
  listingConfig: ListingStrategyConfig;
  volScannerConfig: VolScannerConfig;
  onTrendConfigChange: (config: TrendStrategyConfig) => void;
  onScalpConfigChange: (config: ScalpStrategyConfig) => void;
  onMomentumConfigChange: (config: MomentumStrategyConfig) => void;
  onMemeConfigChange: (config: MemeStrategyConfig) => void;
  onListingConfigChange: (config: ListingStrategyConfig) => void;
  onVolScannerConfigChange: (config: VolScannerConfig) => void;
}

export function SettingsModal({
  open,
  onOpenChange,
  globalSettings,
  onGlobalSettingsChange,
  trendConfig,
  scalpConfig,
  momentumConfig,
  memeConfig,
  listingConfig,
  volScannerConfig,
  onTrendConfigChange,
  onScalpConfigChange,
  onMomentumConfigChange,
  onMemeConfigChange,
  onListingConfigChange,
  onVolScannerConfigChange,
}: SettingsModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden bg-zinc-900/95 backdrop-blur-xl border-zinc-800">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-zinc-100">
            <Settings className="w-5 h-5" />
            Configuration Center
          </DialogTitle>
          <DialogDescription className="text-zinc-500">
            Configure global risk parameters and strategy-specific settings
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="global" className="flex-1 overflow-hidden flex flex-col">
          <TabsList className="grid w-full grid-cols-7 bg-zinc-800/50">
            <TabsTrigger value="global" className="text-xs">
              <Shield className="w-3 h-3 mr-1" />
              Global
            </TabsTrigger>
            <TabsTrigger value="trend" className="text-xs">
              <TrendingUp className="w-3 h-3 mr-1" />
              Trend
            </TabsTrigger>
            <TabsTrigger value="scalp" className="text-xs">
              <Zap className="w-3 h-3 mr-1" />
              Scalp
            </TabsTrigger>
            <TabsTrigger value="momentum" className="text-xs">
              <Rocket className="w-3 h-3 mr-1" />
              Momentum
            </TabsTrigger>
            <TabsTrigger value="meme" className="text-xs">
              <TrendingDown className="w-3 h-3 mr-1" />
              Meme
            </TabsTrigger>
            <TabsTrigger value="listing" className="text-xs">
              <DollarSign className="w-3 h-3 mr-1" />
              Listing
            </TabsTrigger>
            <TabsTrigger value="volscan" className="text-xs">
              <Activity className="w-3 h-3 mr-1" />
              VolScan
            </TabsTrigger>
          </TabsList>

          <div className="flex-1 overflow-y-auto mt-4 px-1">
            {/* Global Settings */}
            <TabsContent value="global" className="space-y-6 mt-0">
              <div className="space-y-4">
                <div>
                  <h3 className="text-sm text-zinc-300 mb-4">Risk Management</h3>
                  <div className="space-y-4">
                    <SettingSlider
                      label="Leverage Cap"
                      value={globalSettings.leverageCap}
                      min={1}
                      max={20}
                      step={1}
                      suffix="x"
                      onChange={(value) =>
                        onGlobalSettingsChange({ ...globalSettings, leverageCap: value })
                      }
                    />
                    <SettingSlider
                      label="Per Trade Risk"
                      value={globalSettings.perTradePercent}
                      min={0.1}
                      max={5}
                      step={0.1}
                      suffix="%"
                      onChange={(value) =>
                        onGlobalSettingsChange({ ...globalSettings, perTradePercent: value })
                      }
                    />
                    <SettingInput
                      label="Max Positions"
                      type="number"
                      value={globalSettings.maxPositions}
                      onChange={(value) =>
                        onGlobalSettingsChange({
                          ...globalSettings,
                          maxPositions: parseInt(value) || 0,
                        })
                      }
                    />
                    <SettingSlider
                      label="Daily Loss Stop"
                      value={globalSettings.dailyLossStop}
                      min={1}
                      max={20}
                      step={0.5}
                      suffix="%"
                      onChange={(value) =>
                        onGlobalSettingsChange({ ...globalSettings, dailyLossStop: value })
                      }
                    />
                  </div>
                </div>

                <Separator className="bg-zinc-800" />

                <div>
                  <h3 className="text-sm text-zinc-300 mb-4">Circuit Breaker</h3>
                  <div className="space-y-4">
                    <SettingSwitch
                      label="Enable Circuit Breaker"
                      checked={globalSettings.circuitBreakerEnabled}
                      onChange={(checked) =>
                        onGlobalSettingsChange({
                          ...globalSettings,
                          circuitBreakerEnabled: checked,
                        })
                      }
                      description="Automatically halt trading when drawdown exceeds threshold"
                    />
                    {globalSettings.circuitBreakerEnabled && (
                      <SettingSlider
                        label="Threshold"
                        value={globalSettings.circuitBreakerThreshold}
                        min={5}
                        max={30}
                        step={1}
                        suffix="%"
                        onChange={(value) =>
                          onGlobalSettingsChange({
                            ...globalSettings,
                            circuitBreakerThreshold: value,
                          })
                        }
                      />
                    )}
                  </div>
                </div>
              </div>
            </TabsContent>

            {/* Trend Strategy */}
            <TabsContent value="trend" className="space-y-6 mt-0">
              <div className="space-y-4">
                <SettingInput
                  label="Moving Average Length"
                  type="number"
                  value={trendConfig.maLength}
                  onChange={(value) =>
                    onTrendConfigChange({ ...trendConfig, maLength: parseInt(value) || 0 })
                  }
                />
                <SettingSlider
                  label="RSI Threshold"
                  value={trendConfig.rsiThreshold}
                  min={20}
                  max={80}
                  step={5}
                  onChange={(value) =>
                    onTrendConfigChange({ ...trendConfig, rsiThreshold: value })
                  }
                />
                <SettingInput
                  label="Cooldown Period"
                  type="number"
                  value={trendConfig.cooldownMinutes}
                  suffix="minutes"
                  onChange={(value) =>
                    onTrendConfigChange({
                      ...trendConfig,
                      cooldownMinutes: parseInt(value) || 0,
                    })
                  }
                />
                <SettingSlider
                  label="Trailing Stop"
                  value={trendConfig.trailingStopPercent}
                  min={0.5}
                  max={10}
                  step={0.5}
                  suffix="%"
                  onChange={(value) =>
                    onTrendConfigChange({ ...trendConfig, trailingStopPercent: value })
                  }
                />
              </div>
            </TabsContent>

            {/* Scalp Strategy */}
            <TabsContent value="scalp" className="space-y-6 mt-0">
              <div className="space-y-4">
                <SettingSlider
                  label="Target Spread"
                  value={scalpConfig.spreadPercent}
                  min={0.05}
                  max={1}
                  step={0.05}
                  suffix="%"
                  onChange={(value) =>
                    onScalpConfigChange({ ...scalpConfig, spreadPercent: value })
                  }
                />
                <SettingSlider
                  label="Stop Loss"
                  value={scalpConfig.stopPercent}
                  min={0.1}
                  max={2}
                  step={0.1}
                  suffix="%"
                  onChange={(value) => onScalpConfigChange({ ...scalpConfig, stopPercent: value })}
                />
                <SettingSelect
                  label="Order Type"
                  value={scalpConfig.orderType}
                  options={[
                    { value: 'limit', label: 'Limit' },
                    { value: 'market', label: 'Market' },
                  ]}
                  onChange={(value) =>
                    onScalpConfigChange({ ...scalpConfig, orderType: value as 'limit' | 'market' })
                  }
                />
                <SettingInput
                  label="Max Scalps Per Day"
                  type="number"
                  value={scalpConfig.maxScalpsPerDay}
                  onChange={(value) =>
                    onScalpConfigChange({
                      ...scalpConfig,
                      maxScalpsPerDay: parseInt(value) || 0,
                    })
                  }
                />
              </div>
            </TabsContent>

            {/* Momentum Strategy */}
            <TabsContent value="momentum" className="space-y-6 mt-0">
              <div className="space-y-4">
                <SettingSlider
                  label="Surge Threshold"
                  value={momentumConfig.surgePercent}
                  min={1}
                  max={20}
                  step={0.5}
                  suffix="%"
                  onChange={(value) =>
                    onMomentumConfigChange({ ...momentumConfig, surgePercent: value })
                  }
                />
                <SettingSlider
                  label="Trailing Stop"
                  value={momentumConfig.trailingStopPercent}
                  min={1}
                  max={15}
                  step={0.5}
                  suffix="%"
                  onChange={(value) =>
                    onMomentumConfigChange({ ...momentumConfig, trailingStopPercent: value })
                  }
                />
                <SettingSwitch
                  label="Skip Pumped Assets"
                  checked={momentumConfig.skipPumped}
                  onChange={(checked) =>
                    onMomentumConfigChange({ ...momentumConfig, skipPumped: checked })
                  }
                  description="Avoid assets that already experienced recent surge"
                />
                <SettingInput
                  label="Lookback Period"
                  type="number"
                  value={momentumConfig.lookbackMinutes}
                  suffix="minutes"
                  onChange={(value) =>
                    onMomentumConfigChange({
                      ...momentumConfig,
                      lookbackMinutes: parseInt(value) || 0,
                    })
                  }
                />
              </div>
            </TabsContent>

            {/* Meme Strategy */}
            <TabsContent value="meme" className="space-y-6 mt-0">
              <div className="space-y-4">
                <SettingSlider
                  label="Sentiment Threshold"
                  value={memeConfig.sentimentThreshold}
                  min={0}
                  max={100}
                  step={5}
                  onChange={(value) =>
                    onMemeConfigChange({ ...memeConfig, sentimentThreshold: value })
                  }
                />
                <div>
                  <h4 className="text-sm text-zinc-400 mb-3">Data Sources</h4>
                  <div className="space-y-3">
                    <SettingSwitch
                      label="Twitter/X"
                      checked={memeConfig.twitterEnabled}
                      onChange={(checked) =>
                        onMemeConfigChange({ ...memeConfig, twitterEnabled: checked })
                      }
                    />
                    <SettingSwitch
                      label="Reddit"
                      checked={memeConfig.redditEnabled}
                      onChange={(checked) =>
                        onMemeConfigChange({ ...memeConfig, redditEnabled: checked })
                      }
                    />
                    <SettingSwitch
                      label="Telegram"
                      checked={memeConfig.telegramEnabled}
                      onChange={(checked) =>
                        onMemeConfigChange({ ...memeConfig, telegramEnabled: checked })
                      }
                    />
                  </div>
                </div>
                <SettingInput
                  label="Position Size Cap"
                  type="number"
                  value={memeConfig.sizeCap}
                  prefix="$"
                  onChange={(value) =>
                    onMemeConfigChange({ ...memeConfig, sizeCap: parseInt(value) || 0 })
                  }
                />
              </div>
            </TabsContent>

            {/* Listing Strategy */}
            <TabsContent value="listing" className="space-y-6 mt-0">
              <div className="space-y-4">
                <SettingSwitch
                  label="Auto-Buy New Listings"
                  checked={listingConfig.autoBuy}
                  onChange={(checked) =>
                    onListingConfigChange({ ...listingConfig, autoBuy: checked })
                  }
                  description="Automatically purchase when new tokens are listed"
                />
                <SettingSlider
                  label="Max Slippage"
                  value={listingConfig.maxSlippagePercent}
                  min={0.5}
                  max={10}
                  step={0.5}
                  suffix="%"
                  onChange={(value) =>
                    onListingConfigChange({ ...listingConfig, maxSlippagePercent: value })
                  }
                />
                <SettingSlider
                  label="Take Profit"
                  value={listingConfig.takeProfitPercent}
                  min={5}
                  max={200}
                  step={5}
                  suffix="%"
                  onChange={(value) =>
                    onListingConfigChange({ ...listingConfig, takeProfitPercent: value })
                  }
                />
                <SettingSlider
                  label="Stop Loss"
                  value={listingConfig.stopLossPercent}
                  min={5}
                  max={80}
                  step={5}
                  suffix="%"
                  onChange={(value) =>
                    onListingConfigChange({ ...listingConfig, stopLossPercent: value })
                  }
                />
              </div>
            </TabsContent>

            {/* Volume Scanner */}
            <TabsContent value="volscan" className="space-y-6 mt-0">
              <div className="space-y-4">
                <SettingSlider
                  label="Volume Spike Threshold"
                  value={volScannerConfig.spikePercent}
                  min={100}
                  max={1000}
                  step={50}
                  suffix="%"
                  onChange={(value) =>
                    onVolScannerConfigChange({ ...volScannerConfig, spikePercent: value })
                  }
                />
                <SettingSelect
                  label="Action Mode"
                  value={volScannerConfig.mode}
                  options={[
                    { value: 'alert', label: 'Alert Only' },
                    { value: 'trade', label: 'Auto Trade' },
                  ]}
                  onChange={(value) =>
                    onVolScannerConfigChange({
                      ...volScannerConfig,
                      mode: value as 'alert' | 'trade',
                    })
                  }
                />
                <SettingInput
                  label="Minimum Volume"
                  type="number"
                  value={volScannerConfig.minVolume}
                  prefix="$"
                  onChange={(value) =>
                    onVolScannerConfigChange({
                      ...volScannerConfig,
                      minVolume: parseInt(value) || 0,
                    })
                  }
                />
              </div>
            </TabsContent>
          </div>
        </Tabs>

        <div className="flex justify-end gap-2 pt-4 border-t border-zinc-800">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => onOpenChange(false)} className="bg-cyan-500 hover:bg-cyan-600">
            Save Changes
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Helper components
function SettingSlider({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-zinc-400">{label}</Label>
        <span className="text-xs text-zinc-300 font-mono">
          {value}
          {suffix}
        </span>
      </div>
      <Slider
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
        className="w-full"
      />
    </div>
  );
}

function SettingInput({
  label,
  type,
  value,
  prefix,
  suffix,
  onChange,
}: {
  label: string;
  type: string;
  value: number;
  prefix?: string;
  suffix?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-zinc-400">{label}</Label>
      <div className="flex items-center gap-2">
        {prefix && <span className="text-xs text-zinc-500">{prefix}</span>}
        <Input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="bg-zinc-800/50 border-zinc-700 text-zinc-200"
        />
        {suffix && <span className="text-xs text-zinc-500">{suffix}</span>}
      </div>
    </div>
  );
}

function SettingSwitch({
  label,
  checked,
  onChange,
  description,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="space-y-0.5">
        <Label className="text-xs text-zinc-400">{label}</Label>
        {description && <p className="text-xs text-zinc-600">{description}</p>}
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

function SettingSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-zinc-400">{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="bg-zinc-800/50 border-zinc-700 text-zinc-200">
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="bg-zinc-800 border-zinc-700">
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value} className="text-zinc-200">
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
