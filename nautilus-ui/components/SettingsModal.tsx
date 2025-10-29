"use client";

import { ChangeEvent } from "react";
import { X, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type {
  GlobalSettings,
  TrendStrategyConfig,
  ScalpStrategyConfig,
  MomentumStrategyConfig,
  MemeStrategyConfig,
  ListingStrategyConfig,
  VolScannerConfig,
} from "@/lib/types";

interface SettingsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  globalSettings: GlobalSettings;
  onGlobalSettingsChange: (value: GlobalSettings) => void;
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
  if (!open) return null;

  const handleNumberChange = <T extends object>(
    current: T,
    updater: (next: T) => void,
    field: keyof T,
  ) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      const value = Number(event.target.value);
      updater({ ...current, [field]: Number.isNaN(value) ? 0 : value });
    };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={() => onOpenChange(false)} />
      <div className="relative w-full max-w-3xl max-h-[85vh] overflow-y-auto rounded-2xl border border-zinc-800 bg-zinc-900/95 backdrop-blur-xl p-6 space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h2 className="text-lg text-zinc-100 flex items-center gap-2">
              <Shield className="w-5 h-5" />
              Configuration Center
            </h2>
            <p className="text-sm text-zinc-500">Adjust global risk rails and strategy presets.</p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => onOpenChange(false)}>
            <X className="w-4 h-4" />
          </Button>
        </header>

        <section className="space-y-4">
          <h3 className="text-sm text-zinc-300">Global Risk Settings</h3>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Leverage Cap" value={globalSettings.leverageCap} onChange={handleNumberChange(globalSettings, onGlobalSettingsChange, "leverageCap")} suffix="x" />
            <Field label="Per Trade Risk" value={globalSettings.perTradePercent} onChange={handleNumberChange(globalSettings, onGlobalSettingsChange, "perTradePercent")} suffix="%" step="0.1" />
            <Field label="Max Positions" value={globalSettings.maxPositions} onChange={handleNumberChange(globalSettings, onGlobalSettingsChange, "maxPositions")} />
            <Field label="Daily Loss Stop" value={globalSettings.dailyLossStop} onChange={handleNumberChange(globalSettings, onGlobalSettingsChange, "dailyLossStop")} suffix="%" step="0.5" />
          </div>
          <div className="flex items-center justify-between rounded-lg border border-zinc-800/70 bg-zinc-800/30 px-4 py-3">
            <div>
              <p className="text-sm text-zinc-200">Circuit Breaker</p>
              <p className="text-xs text-zinc-500">Automatically halt trading when drawdown exceeds threshold.</p>
            </div>
            <Switch
              checked={globalSettings.circuitBreakerEnabled}
              onCheckedChange={(checked) =>
                onGlobalSettingsChange({
                  ...globalSettings,
                  circuitBreakerEnabled: checked,
                })
              }
            />
          </div>
          {globalSettings.circuitBreakerEnabled && (
            <Field
              label="Circuit Breaker Threshold"
              value={globalSettings.circuitBreakerThreshold}
              onChange={handleNumberChange(globalSettings, onGlobalSettingsChange, "circuitBreakerThreshold")}
              suffix="%"
            />
          )}
        </section>

        <Divider />

        <StrategySection
          title="Trend Strategy"
          description="Control moving averages and trailing stops for primary trend model."
        >
          <div className="grid grid-cols-2 gap-4">
            <Field label="MA Length" value={trendConfig.maLength} onChange={handleNumberChange(trendConfig, onTrendConfigChange, "maLength")} />
            <Field label="RSI Threshold" value={trendConfig.rsiThreshold} onChange={handleNumberChange(trendConfig, onTrendConfigChange, "rsiThreshold")} />
            <Field label="Cooldown (min)" value={trendConfig.cooldownMinutes} onChange={handleNumberChange(trendConfig, onTrendConfigChange, "cooldownMinutes")} />
            <Field label="Trailing Stop" value={trendConfig.trailingStopPercent} onChange={handleNumberChange(trendConfig, onTrendConfigChange, "trailingStopPercent")} suffix="%" step="0.1" />
          </div>
        </StrategySection>

        <StrategySection
          title="Scalp Strategy"
          description="Fine tune scalping behaviour across venues."
        >
          <div className="grid grid-cols-2 gap-4">
            <Field label="Spread %" value={scalpConfig.spreadPercent} onChange={handleNumberChange(scalpConfig, onScalpConfigChange, "spreadPercent")} step="0.1" />
            <Field label="Stop %" value={scalpConfig.stopPercent} onChange={handleNumberChange(scalpConfig, onScalpConfigChange, "stopPercent")} step="0.1" />
            <Dropdown
              label="Order Type"
              value={scalpConfig.orderType}
              options={["limit", "market"]}
              onChange={(value) => onScalpConfigChange({ ...scalpConfig, orderType: value as "limit" | "market" })}
            />
            <Field label="Max Scalps / Day" value={scalpConfig.maxScalpsPerDay} onChange={handleNumberChange(scalpConfig, onScalpConfigChange, "maxScalpsPerDay")} />
          </div>
        </StrategySection>

        <StrategySection title="Momentum Strategy" description="Manage surge detection and trailing stops.">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Surge %" value={momentumConfig.surgePercent} onChange={handleNumberChange(momentumConfig, onMomentumConfigChange, "surgePercent")} step="0.1" />
            <Field label="Trailing Stop %" value={momentumConfig.trailingStopPercent} onChange={handleNumberChange(momentumConfig, onMomentumConfigChange, "trailingStopPercent")} step="0.1" />
            <Toggle
              label="Skip Pumped Markets"
              checked={momentumConfig.skipPumped}
              onCheckedChange={(checked) => onMomentumConfigChange({ ...momentumConfig, skipPumped: checked })}
            />
            <Field label="Lookback (min)" value={momentumConfig.lookbackMinutes} onChange={handleNumberChange(momentumConfig, onMomentumConfigChange, "lookbackMinutes")} />
          </div>
        </StrategySection>

        <StrategySection title="Meme Strategy" description="Social sentiment thresholds and channel controls.">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Sentiment Threshold" value={memeConfig.sentimentThreshold} onChange={handleNumberChange(memeConfig, onMemeConfigChange, "sentimentThreshold")} />
            <Field label="Position Size Cap" value={memeConfig.sizeCap} onChange={handleNumberChange(memeConfig, onMemeConfigChange, "sizeCap")} />
            <Toggle
              label="Twitter"
              checked={memeConfig.twitterEnabled}
              onCheckedChange={(checked) => onMemeConfigChange({ ...memeConfig, twitterEnabled: checked })}
            />
            <Toggle
              label="Reddit"
              checked={memeConfig.redditEnabled}
              onCheckedChange={(checked) => onMemeConfigChange({ ...memeConfig, redditEnabled: checked })}
            />
            <Toggle
              label="Telegram"
              checked={memeConfig.telegramEnabled}
              onCheckedChange={(checked) => onMemeConfigChange({ ...memeConfig, telegramEnabled: checked })}
            />
          </div>
        </StrategySection>

        <StrategySection title="Listing Strategy" description="Risk guardrails around token listings.">
          <div className="grid grid-cols-2 gap-4">
            <Toggle
              label="Enable Auto Buy"
              checked={listingConfig.autoBuy}
              onCheckedChange={(checked) => onListingConfigChange({ ...listingConfig, autoBuy: checked })}
            />
            <Field label="Slippage %" value={listingConfig.maxSlippagePercent} onChange={handleNumberChange(listingConfig, onListingConfigChange, "maxSlippagePercent")} step="0.1" />
            <Field label="Take Profit %" value={listingConfig.takeProfitPercent} onChange={handleNumberChange(listingConfig, onListingConfigChange, "takeProfitPercent")} step="0.1" />
            <Field label="Stop Loss %" value={listingConfig.stopLossPercent} onChange={handleNumberChange(listingConfig, onListingConfigChange, "stopLossPercent")} step="0.1" />
          </div>
        </StrategySection>

        <StrategySection title="Vol Scanner" description="Reaction mode and spike detection thresholds.">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Spike %" value={volScannerConfig.spikePercent} onChange={handleNumberChange(volScannerConfig, onVolScannerConfigChange, "spikePercent")} />
            <Dropdown
              label="Reaction Mode"
              value={volScannerConfig.mode}
              options={["alert", "trade"]}
              onChange={(value) => onVolScannerConfigChange({ ...volScannerConfig, mode: value as "alert" | "trade" })}
            />
            <Field label="Minimum Volume" value={volScannerConfig.minVolume} onChange={handleNumberChange(volScannerConfig, onVolScannerConfigChange, "minVolume")} />
          </div>
        </StrategySection>
      </div>
    </div>
  );
}

function Divider() {
  return <div className="h-px bg-zinc-800" />;
}

function StrategySection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-sm text-zinc-300">{title}</h3>
        <p className="text-xs text-zinc-500">{description}</p>
      </div>
      {children}
    </section>
  );
}

interface FieldProps {
  label: string;
  value: number;
  suffix?: string;
  step?: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}

function Field({ label, value, suffix, step, onChange }: FieldProps) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-400">
      {label}
      <div className="relative">
        <input
          type="number"
          value={value}
          step={step}
          onChange={onChange}
          className="w-full rounded-lg border border-zinc-800/60 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-400/40"
        />
        {suffix && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500">{suffix}</span>}
      </div>
    </label>
  );
}

function Toggle({ label, checked, onCheckedChange }: { label: string; checked: boolean; onCheckedChange: (checked: boolean) => void }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-zinc-800/60 bg-zinc-800/20 px-3 py-2">
      <span className="text-xs text-zinc-300">{label}</span>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

interface DropdownProps {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}

function Dropdown({ label, value, options, onChange }: DropdownProps) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-zinc-800/60 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-400/40"
      >
        {options.map((option) => (
          <option key={option} value={option} className="text-zinc-900">
            {option.toUpperCase()}
          </option>
        ))}
      </select>
    </label>
  );
}
