import { Bell, Activity, Info, AlertTriangle, XCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

import { Badge } from './ui/badge';
import { ScrollArea } from './ui/scroll-area';
import type { Alert, Trade } from '../types/trading';


interface BottomBarProps {
  alerts: Alert[];
  recentTrades: Trade[];
}

export function BottomBar({ alerts, recentTrades }: BottomBarProps) {
  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="h-48 bg-zinc-900/70 backdrop-blur-xl border-t border-zinc-800/50 flex"
    >
      {/* Alerts Feed */}
      <div className="flex-1 border-r border-zinc-800/50">
        <div className="flex items-center gap-2 px-6 py-3 border-b border-zinc-800/50">
          <Bell className="w-4 h-4 text-zinc-400" />
          <h3 className="text-zinc-300">Alerts</h3>
          <Badge variant="outline" className="text-xs border-zinc-700/50 text-zinc-500 ml-auto">
            {alerts.length}
          </Badge>
        </div>
        <ScrollArea className="h-[156px]">
          <div className="px-6 py-2 space-y-1">
            <AnimatePresence>
              {alerts.map((alert) => (
                <AlertItem key={alert.id} alert={alert} formatTime={formatTime} />
              ))}
            </AnimatePresence>
          </div>
        </ScrollArea>
      </div>

      {/* Recent Trades */}
      <div className="flex-1">
        <div className="flex items-center gap-2 px-6 py-3 border-b border-zinc-800/50">
          <Activity className="w-4 h-4 text-zinc-400" />
          <h3 className="text-zinc-300">Recent Trades</h3>
          <Badge variant="outline" className="text-xs border-zinc-700/50 text-zinc-500 ml-auto">
            {recentTrades.length}
          </Badge>
        </div>
        <ScrollArea className="h-[156px]">
          <div className="px-6 py-2 space-y-1">
            {recentTrades.slice(0, 10).map((trade) => (
              <TradeItem key={trade.id} trade={trade} formatTime={formatTime} formatCurrency={formatCurrency} />
            ))}
          </div>
        </ScrollArea>
      </div>
    </motion.div>
  );
}

function AlertItem({ alert, formatTime }: { alert: Alert; formatTime: (ts: number) => string }) {
  const getIcon = () => {
    switch (alert.type) {
      case 'info':
        return <Info className="w-3.5 h-3.5 text-cyan-400" />;
      case 'warning':
        return <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />;
      case 'error':
        return <XCircle className="w-3.5 h-3.5 text-red-400" />;
    }
  };

  const getColor = () => {
    switch (alert.type) {
      case 'info':
        return 'border-cyan-400/10 bg-cyan-400/5';
      case 'warning':
        return 'border-amber-400/10 bg-amber-400/5';
      case 'error':
        return 'border-red-400/10 bg-red-400/5';
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className={`flex items-start gap-3 p-2.5 rounded-lg border ${getColor()}`}
    >
      {getIcon()}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-zinc-300">{alert.message}</p>
        <span className="text-xs text-zinc-600 font-mono">{formatTime(alert.timestamp)}</span>
      </div>
    </motion.div>
  );
}

function TradeItem({
  trade,
  formatTime,
  formatCurrency,
}: {
  trade: Trade;
  formatTime: (ts: number) => string;
  formatCurrency: (v: number) => string;
}) {
  return (
    <div className="flex items-center justify-between p-2.5 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50 transition-colors">
      <div className="flex items-center gap-3">
        <Badge
          variant="outline"
          className={`text-xs px-2 py-0 ${
            trade.side === 'buy'
              ? 'border-emerald-400/30 text-emerald-400 bg-emerald-400/10'
              : 'border-red-400/30 text-red-400 bg-red-400/10'
          }`}
        >
          {trade.side.toUpperCase()}
        </Badge>
        <div>
          <span className="text-xs text-zinc-300 font-mono">{trade.symbol}</span>
          <span className="text-xs text-zinc-600 font-mono ml-2">
            {trade.quantity.toFixed(4)} @ {formatCurrency(trade.price)}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-4">
        {trade.pnl !== undefined && (
          <span
            className={`text-xs font-mono ${
              trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {formatCurrency(trade.pnl)}
          </span>
        )}
        <span className="text-xs text-zinc-600 font-mono">{formatTime(trade.timestamp)}</span>
      </div>
    </div>
  );
}
