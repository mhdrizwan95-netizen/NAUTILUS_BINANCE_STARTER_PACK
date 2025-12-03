import { TrendingUp, TrendingDown, Calendar as CalendarIcon, AlertCircle, Info, AlertTriangle } from 'lucide-react';
import { BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import type { StrategyPerformance, Strategy, Trade, Alert } from '../../types/trading';
import { Calendar } from '../ui/calendar';
import { ScrollArea } from '../ui/scroll-area';
import { Badge } from '../ui/badge';
import { useState } from 'react';

interface DashboardTabProps {
  performances: StrategyPerformance[];
  strategies: Strategy[];
  recentTrades: Trade[];
  alerts: Alert[];
}

export function DashboardTab({ performances, strategies, recentTrades, alerts }: DashboardTabProps) {
  const [selectedDate, setSelectedDate] = useState<Date | undefined>(new Date());

  // Calculate aggregate metrics
  const totalPnL = performances.reduce((sum, p) => sum + p.metrics.pnl, 0);
  const totalCapital = strategies.reduce((sum, s) => sum + s.capital, 0);
  const totalPnLPercent = (totalPnL / totalCapital) * 100;
  
  // Mock daily PnL
  const dailyPnL = totalPnL * 0.3; // Assume 30% is today
  const unPnL = totalPnL * 0.15; // Unrealized
  const realizedPnL = totalPnL - unPnL;
  
  const maxDrawdown = Math.max(...performances.map(p => p.metrics.drawdown)) * 100;

  // Strategy performance chart data
  const strategyChartData = strategies
    .filter(s => s.enabled)
    .map(strategy => {
      const strategyPerfs = performances.filter(p => p.strategyId === strategy.id);
      const strategyPnL = strategyPerfs.reduce((sum, p) => sum + p.metrics.pnl, 0);
      const strategyPnLPercent = (strategyPnL / strategy.capital) * 100;
      
      return {
        name: strategy.name,
        pnl: strategyPnL,
        pnlPercent: strategyPnLPercent,
        sharpe: strategyPerfs.reduce((sum, p) => sum + p.metrics.sharpe, 0) / strategyPerfs.length || 0,
        trades: strategyPerfs.reduce((sum, p) => sum + p.metrics.tradeCount, 0),
      };
    });

  // Daily PnL calendar data (mock)
  const getDayPnL = (date: Date) => {
    const seed = date.getDate() + date.getMonth() * 31;
    return (Math.sin(seed) * 1000 + Math.cos(seed * 2) * 500);
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
    <div className="grid grid-cols-12 gap-4 p-6">
      {/* Top Metrics Row */}
      <div className="col-span-12 grid grid-cols-4 gap-4">
        <MetricCard
          label="Total PnL"
          value={formatCurrency(totalPnL)}
          subtitle={`${totalPnLPercent >= 0 ? '+' : ''}${totalPnLPercent.toFixed(2)}%`}
          trend={totalPnL >= 0 ? 'up' : 'down'}
          color={totalPnL >= 0 ? 'emerald' : 'red'}
        />
        <MetricCard
          label="Daily PnL"
          value={formatCurrency(dailyPnL)}
          subtitle="Today's P&L"
          trend={dailyPnL >= 0 ? 'up' : 'down'}
          color={dailyPnL >= 0 ? 'emerald' : 'red'}
        />
        <MetricCard
          label="Unrealized PnL"
          value={formatCurrency(unPnL)}
          subtitle={`Realized: ${formatCurrency(realizedPnL)}`}
          color="cyan"
        />
        <MetricCard
          label="Max Drawdown"
          value={`${maxDrawdown.toFixed(2)}%`}
          subtitle="Peak to trough"
          color={maxDrawdown < 10 ? 'zinc' : 'amber'}
        />
      </div>

      {/* Calendar and Charts Row */}
      <div className="col-span-5 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
        <h3 className="text-zinc-400 mb-4">Calendar PnL</h3>
        <div className="flex flex-col items-center">
          <Calendar
            mode="single"
            selected={selectedDate}
            onSelect={setSelectedDate}
            className="rounded-lg border-zinc-800"
            classNames={{
              months: "flex flex-col",
              month: "space-y-4",
              caption: "flex justify-center pt-1 relative items-center text-zinc-300",
              caption_label: "text-sm",
              nav: "space-x-1 flex items-center",
              nav_button: "h-7 w-7 bg-transparent p-0 opacity-50 hover:opacity-100",
              nav_button_previous: "absolute left-1",
              nav_button_next: "absolute right-1",
              table: "w-full border-collapse space-y-1",
              head_row: "flex",
              head_cell: "text-zinc-500 rounded-md w-9 text-xs",
              row: "flex w-full mt-2",
              cell: "relative p-0 text-center text-sm focus-within:relative focus-within:z-20 [&:has([aria-selected])]:bg-accent",
              day: "h-9 w-9 p-0 font-mono text-xs hover:bg-zinc-800/50 rounded-md",
              day_selected: "bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30",
              day_today: "bg-zinc-800/50 text-zinc-100",
              day_outside: "text-zinc-700 opacity-50",
              day_disabled: "text-zinc-700 opacity-50",
              day_range_middle: "aria-selected:bg-accent aria-selected:text-accent-foreground",
              day_hidden: "invisible",
            }}
            components={{
              DayContent: ({ date }) => {
                const dayPnL = getDayPnL(date);
                const isPositive = dayPnL >= 0;
                return (
                  <div className="flex flex-col items-center justify-center h-full">
                    <span>{date.getDate()}</span>
                    <span className={`text-[8px] ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? '+' : ''}{(dayPnL / 1000).toFixed(1)}k
                    </span>
                  </div>
                );
              }
            }}
          />
          {selectedDate && (
            <div className="mt-4 p-3 bg-zinc-800/50 rounded-lg w-full">
              <p className="text-xs text-zinc-500 mb-1">Selected Date PnL</p>
              <p className={`font-mono ${getDayPnL(selectedDate) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatCurrency(getDayPnL(selectedDate))}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Strategy Performance Chart */}
      <div className="col-span-7 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
        <h3 className="text-zinc-400 mb-4">Strategy Performance</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={strategyChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis dataKey="name" stroke="#71717a" className="text-xs" />
            <YAxis stroke="#71717a" className="text-xs" />
            <Tooltip
              contentStyle={{
                backgroundColor: '#18181b',
                border: '1px solid #3f3f46',
                borderRadius: '8px',
              }}
              labelStyle={{ color: '#a1a1aa' }}
              itemStyle={{ color: '#fafafa' }}
            />
            <Bar dataKey="pnl" fill="#06b6d4" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        
        {/* Strategy Stats Table */}
        <div className="mt-4 space-y-2">
          {strategyChartData.map((strategy) => (
            <div
              key={strategy.name}
              className="flex items-center justify-between p-2 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50 transition-colors"
            >
              <span className="text-sm text-zinc-300">{strategy.name}</span>
              <div className="flex items-center gap-4 font-mono text-xs">
                <span className={strategy.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {formatCurrency(strategy.pnl)}
                </span>
                <span className="text-zinc-500">Sharpe: {strategy.sharpe.toFixed(2)}</span>
                <span className="text-zinc-600">{strategy.trades} trades</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Trades and Alerts Row */}
      <div className="col-span-6 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
        <h3 className="text-zinc-400 mb-4">Recent Trades</h3>
        <ScrollArea className="h-[300px]">
          <div className="space-y-2">
            {recentTrades.slice(0, 15).map((trade) => {
              const strategy = strategies.find(s => s.id === trade.strategyId);
              return (
                <div
                  key={trade.id}
                  className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <Badge 
                      variant={trade.side === 'buy' ? 'default' : 'secondary'}
                      className={`${
                        trade.side === 'buy' 
                          ? 'bg-emerald-500/20 text-emerald-400 border-emerald-400/30' 
                          : 'bg-red-500/20 text-red-400 border-red-400/30'
                      }`}
                    >
                      {trade.side.toUpperCase()}
                    </Badge>
                    <div>
                      <p className="text-sm text-zinc-300 font-mono">{trade.symbol}</p>
                      <p className="text-xs text-zinc-500">{strategy?.name}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-mono text-zinc-300">
                      {trade.quantity.toFixed(4)} @ {formatCurrency(trade.price)}
                    </p>
                    <div className="flex items-center gap-2 justify-end">
                      <p className="text-xs text-zinc-500">{formatTime(trade.timestamp)}</p>
                      {trade.pnl !== undefined && (
                        <p className={`text-xs font-mono ${
                          trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          {trade.pnl >= 0 ? '+' : ''}{formatCurrency(trade.pnl)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </div>

      <div className="col-span-6 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
        <h3 className="text-zinc-400 mb-4">System Alerts</h3>
        <ScrollArea className="h-[300px]">
          <div className="space-y-2">
            {alerts.map((alert) => {
              const alertConfig = {
                info: {
                  icon: <Info className="w-4 h-4" />,
                  color: 'text-cyan-400',
                  bgColor: 'bg-cyan-500/10',
                  borderColor: 'border-cyan-400/30',
                },
                warning: {
                  icon: <AlertTriangle className="w-4 h-4" />,
                  color: 'text-amber-400',
                  bgColor: 'bg-amber-500/10',
                  borderColor: 'border-amber-400/30',
                },
                error: {
                  icon: <AlertCircle className="w-4 h-4" />,
                  color: 'text-red-400',
                  bgColor: 'bg-red-500/10',
                  borderColor: 'border-red-400/30',
                },
              };

              const config = alertConfig[alert.type];

              return (
                <div
                  key={alert.id}
                  className={`flex items-start gap-3 p-3 rounded-lg border ${config.bgColor} ${config.borderColor} hover:brightness-110 transition-all`}
                >
                  <div className={config.color}>
                    {config.icon}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-zinc-300">{alert.message}</p>
                    <p className="text-xs text-zinc-500 mt-1">{formatTime(alert.timestamp)}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  subtitle?: string;
  trend?: 'up' | 'down';
  color: 'emerald' | 'red' | 'cyan' | 'amber' | 'zinc';
}

function MetricCard({ label, value, subtitle, trend, color }: MetricCardProps) {
  const colorClasses = {
    emerald: 'text-emerald-400 border-emerald-400/30',
    red: 'text-red-400 border-red-400/30',
    cyan: 'text-cyan-400 border-cyan-400/30',
    amber: 'text-amber-400 border-amber-400/30',
    zinc: 'text-zinc-400 border-zinc-700/30',
  };

  return (
    <div className={`bg-zinc-900/50 backdrop-blur-sm border ${colorClasses[color]} rounded-xl p-4`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-zinc-500">{label}</span>
        {trend && (
          trend === 'up' ? (
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          ) : (
            <TrendingDown className="w-4 h-4 text-red-400" />
          )
        )}
      </div>
      <div className={`font-mono ${colorClasses[color].split(' ')[0]}`}>
        {value}
      </div>
      {subtitle && (
        <div className="text-xs text-zinc-600 mt-1 font-mono">{subtitle}</div>
      )}
    </div>
  );
}
