import { Shield, AlertTriangle, Lock, Zap, Database, Bell } from 'lucide-react';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Switch } from '../ui/switch';
import { Slider } from '../ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Button } from '../ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { useState } from 'react';

export function SettingsTab() {
  return (
    <div className="p-6">
      <Tabs defaultValue="engine" className="w-full">
        <TabsList className="bg-zinc-800/50 border border-zinc-700/50 mb-6">
          <TabsTrigger value="engine" className="gap-2">
            <Zap className="w-4 h-4" />
            Engine
          </TabsTrigger>
          <TabsTrigger value="risk" className="gap-2">
            <Shield className="w-4 h-4" />
            Risk & Guardrails
          </TabsTrigger>
          <TabsTrigger value="policy" className="gap-2">
            <Lock className="w-4 h-4" />
            Policy
          </TabsTrigger>
          <TabsTrigger value="notifications" className="gap-2">
            <Bell className="w-4 h-4" />
            Notifications
          </TabsTrigger>
        </TabsList>

        <TabsContent value="engine">
          <EngineSettings />
        </TabsContent>

        <TabsContent value="risk">
          <RiskSettings />
        </TabsContent>

        <TabsContent value="policy">
          <PolicySettings />
        </TabsContent>

        <TabsContent value="notifications">
          <NotificationSettings />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function EngineSettings() {
  return (
    <div className="grid grid-cols-2 gap-6">
      <SettingsSection
        title="Execution Engine"
        icon={<Zap className="w-5 h-5 text-cyan-400" />}
      >
        <SettingRow label="Order Router">
          <Select defaultValue="smart">
            <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="smart">Smart Router</SelectItem>
              <SelectItem value="aggressive">Aggressive Fill</SelectItem>
              <SelectItem value="passive">Passive Queue</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>

        <SettingRow label="Max Order Rate (per sec)">
          <div className="space-y-2">
            <Slider
              defaultValue={[10]}
              max={50}
              step={1}
              className="[&_[role=slider]]:bg-cyan-400 [&_[role=slider]]:border-cyan-400"
            />
            <span className="text-xs text-zinc-500 font-mono">10 orders/sec</span>
          </div>
        </SettingRow>

        <SettingRow label="Default Order Type">
          <Select defaultValue="limit">
            <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="limit">Limit</SelectItem>
              <SelectItem value="market">Market</SelectItem>
              <SelectItem value="stop-limit">Stop Limit</SelectItem>
              <SelectItem value="iceberg">Iceberg</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>

        <SettingRow label="Enable Post-Only Mode">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Auto-Cancel Timeout (sec)">
          <Input
            type="number"
            defaultValue="60"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="Performance"
        icon={<Database className="w-5 h-5 text-emerald-400" />}
      >
        <SettingRow label="Data Refresh Rate (ms)">
          <Select defaultValue="100">
            <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="50">50ms (High CPU)</SelectItem>
              <SelectItem value="100">100ms (Recommended)</SelectItem>
              <SelectItem value="250">250ms (Low CPU)</SelectItem>
              <SelectItem value="500">500ms (Minimal)</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>

        <SettingRow label="Websocket Compression">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Historical Data Cache (GB)">
          <div className="space-y-2">
            <Slider
              defaultValue={[5]}
              max={20}
              step={1}
              className="[&_[role=slider]]:bg-emerald-400 [&_[role=slider]]:border-emerald-400"
            />
            <span className="text-xs text-zinc-500 font-mono">5 GB</span>
          </div>
        </SettingRow>

        <SettingRow label="Log Level">
          <Select defaultValue="info">
            <SelectTrigger className="bg-zinc-800/50 border-zinc-700">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="debug">Debug</SelectItem>
              <SelectItem value="info">Info</SelectItem>
              <SelectItem value="warning">Warning</SelectItem>
              <SelectItem value="error">Error Only</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>
      </SettingsSection>
    </div>
  );
}

function RiskSettings() {
  return (
    <div className="grid grid-cols-2 gap-6">
      <SettingsSection
        title="Position Limits"
        icon={<Shield className="w-5 h-5 text-amber-400" />}
      >
        <SettingRow label="Max Position Size ($)">
          <Input
            type="number"
            defaultValue="50000"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Max Leverage">
          <div className="space-y-2">
            <Slider
              defaultValue={[5]}
              max={20}
              step={1}
              className="[&_[role=slider]]:bg-amber-400 [&_[role=slider]]:border-amber-400"
            />
            <span className="text-xs text-zinc-500 font-mono">5x</span>
          </div>
        </SettingRow>

        <SettingRow label="Max Positions per Strategy">
          <Input
            type="number"
            defaultValue="10"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Max Open Positions Total">
          <Input
            type="number"
            defaultValue="25"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Concentration Limit (%)">
          <div className="space-y-2">
            <Slider
              defaultValue={[20]}
              max={100}
              step={5}
              className="[&_[role=slider]]:bg-amber-400 [&_[role=slider]]:border-amber-400"
            />
            <span className="text-xs text-zinc-500 font-mono">20%</span>
          </div>
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="Circuit Breakers"
        icon={<AlertTriangle className="w-5 h-5 text-red-400" />}
      >
        <SettingRow label="Enable Circuit Breaker">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Daily Loss Limit (%)">
          <div className="space-y-2">
            <Slider
              defaultValue={[10]}
              max={50}
              step={1}
              className="[&_[role=slider]]:bg-red-400 [&_[role=slider]]:border-red-400"
            />
            <span className="text-xs text-zinc-500 font-mono">10%</span>
          </div>
        </SettingRow>

        <SettingRow label="Max Drawdown Threshold (%)">
          <div className="space-y-2">
            <Slider
              defaultValue={[15]}
              max={50}
              step={1}
              className="[&_[role=slider]]:bg-red-400 [&_[role=slider]]:border-red-400"
            />
            <span className="text-xs text-zinc-500 font-mono">15%</span>
          </div>
        </SettingRow>

        <SettingRow label="Consecutive Loss Limit">
          <Input
            type="number"
            defaultValue="5"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Cooldown Period (minutes)">
          <Input
            type="number"
            defaultValue="30"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Auto-Resume After Cooldown">
          <Switch />
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="Stop Loss & Take Profit"
        icon={<Shield className="w-5 h-5 text-violet-400" />}
      >
        <SettingRow label="Default Stop Loss (%)">
          <div className="space-y-2">
            <Slider
              defaultValue={[3]}
              max={20}
              step={0.5}
              className="[&_[role=slider]]:bg-violet-400 [&_[role=slider]]:border-violet-400"
            />
            <span className="text-xs text-zinc-500 font-mono">3%</span>
          </div>
        </SettingRow>

        <SettingRow label="Default Take Profit (%)">
          <div className="space-y-2">
            <Slider
              defaultValue={[8]}
              max={50}
              step={1}
              className="[&_[role=slider]]:bg-violet-400 [&_[role=slider]]:border-violet-400"
            />
            <span className="text-xs text-zinc-500 font-mono">8%</span>
          </div>
        </SettingRow>

        <SettingRow label="Enable Trailing Stop">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Trailing Distance (%)">
          <div className="space-y-2">
            <Slider
              defaultValue={[2]}
              max={10}
              step={0.5}
              className="[&_[role=slider]]:bg-violet-400 [&_[role=slider]]:border-violet-400"
            />
            <span className="text-xs text-zinc-500 font-mono">2%</span>
          </div>
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="Venue Specific Limits"
        icon={<Database className="w-5 h-5 text-cyan-400" />}
      >
        <SettingRow label="Binance Max Position ($)">
          <Input
            type="number"
            defaultValue="100000"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="IBKR Max Position ($)">
          <Input
            type="number"
            defaultValue="200000"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Per-Venue Leverage Cap">
          <div className="space-y-2">
            <Slider
              defaultValue={[3]}
              max={10}
              step={1}
              className="[&_[role=slider]]:bg-cyan-400 [&_[role=slider]]:border-cyan-400"
            />
            <span className="text-xs text-zinc-500 font-mono">3x</span>
          </div>
        </SettingRow>
      </SettingsSection>
    </div>
  );
}

function PolicySettings() {
  return (
    <div className="grid grid-cols-2 gap-6">
      <SettingsSection
        title="Trading Hours"
        icon={<Lock className="w-5 h-5 text-violet-400" />}
      >
        <SettingRow label="Enable Trading Hours">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Start Time (UTC)">
          <Input
            type="time"
            defaultValue="00:00"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="End Time (UTC)">
          <Input
            type="time"
            defaultValue="23:59"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Trade on Weekends">
          <Switch defaultChecked />
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="Compliance"
        icon={<Shield className="w-5 h-5 text-amber-400" />}
      >
        <SettingRow label="Require Manual Approval for Live">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Enable Audit Trail">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Max Daily Trade Volume ($)">
          <Input
            type="number"
            defaultValue="1000000"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Prohibited Symbols">
          <Input
            placeholder="SYMBOL1, SYMBOL2..."
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="API Keys & Secrets"
        icon={<Lock className="w-5 h-5 text-red-400" />}
      >
        <SettingRow label="Binance API Key">
          <Input
            type="password"
            placeholder="••••••••••••••••"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="IBKR Username">
          <Input
            type="text"
            placeholder="Username"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="OANDA Token">
          <Input
            type="password"
            placeholder="••••••••••••••••"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <Button variant="outline" className="w-full">
          Rotate All Keys
        </Button>
      </SettingsSection>

      <SettingsSection
        title="Emergency Contacts"
        icon={<AlertTriangle className="w-5 h-5 text-red-400" />}
      >
        <SettingRow label="Primary Email">
          <Input
            type="email"
            placeholder="trader@example.com"
            className="bg-zinc-800/50 border-zinc-700"
          />
        </SettingRow>

        <SettingRow label="SMS Number">
          <Input
            type="tel"
            placeholder="+1 234 567 8900"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>

        <SettingRow label="Slack Webhook">
          <Input
            type="url"
            placeholder="https://hooks.slack.com/..."
            className="bg-zinc-800/50 border-zinc-700 text-xs"
          />
        </SettingRow>
      </SettingsSection>
    </div>
  );
}

function NotificationSettings() {
  return (
    <div className="grid grid-cols-2 gap-6">
      <SettingsSection
        title="Alert Preferences"
        icon={<Bell className="w-5 h-5 text-cyan-400" />}
      >
        <SettingRow label="Trade Execution Alerts">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Order Rejection Alerts">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="PnL Threshold Alerts">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Venue Connection Status">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Strategy Performance Alerts">
          <Switch />
        </SettingRow>

        <SettingRow label="Minimum Alert Interval (sec)">
          <Input
            type="number"
            defaultValue="60"
            className="bg-zinc-800/50 border-zinc-700 font-mono"
          />
        </SettingRow>
      </SettingsSection>

      <SettingsSection
        title="Notification Channels"
        icon={<Bell className="w-5 h-5 text-emerald-400" />}
      >
        <SettingRow label="In-App Notifications">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Email Notifications">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="SMS Notifications">
          <Switch />
        </SettingRow>

        <SettingRow label="Slack Notifications">
          <Switch defaultChecked />
        </SettingRow>

        <SettingRow label="Telegram Notifications">
          <Switch />
        </SettingRow>

        <SettingRow label="Sound Alerts">
          <Switch defaultChecked />
        </SettingRow>
      </SettingsSection>
    </div>
  );
}

function SettingsSection({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h3 className="text-zinc-300">{title}</h3>
      </div>
      <div className="space-y-4">
        {children}
      </div>
    </div>
  );
}

function SettingRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-zinc-400">{label}</Label>
      {children}
    </div>
  );
}
