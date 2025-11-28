/**
 * Virtualized Trade Log - Handles 10,000+ rows without performance degradation
 * 
 * Uses TanStack Virtual for efficient row rendering (only visible rows in DOM)
 */
import { useVirtualizer } from '@tanstack/react-virtual';
import { useRef } from 'react';
import { useRecentTrades } from '@/lib/tradingStore';
import { cn } from '@/lib/utils';

export function VirtualizedTradeLog({ limit = 10000 }: { limit?: number }) {
    const trades = useRecentTrades(limit);
    const parentRef = useRef<HTMLDivElement>(null);

    const rowVirtualizer = useVirtualizer({
        count: trades.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 48, // Row height in pixels
        overscan: 10, // Render 10 extra rows above/below viewport
    });

    return (
        <div className="glass-panel h-full flex flex-col">
            <div className="px-4 py-2 border-b border-cyber-glass-border">
                <h3 className="text-sm font-medium cyber-positive">Trade Log</h3>
                <p className="text-xs text-cyber-text-dim">{trades.length.toLocaleString()} trades</p>
            </div>

            {/* Header */}
            <div className="grid grid-cols-8 gap-2 px-4 py-2 text-xs font-mono text-cyber-text-dim border-b border-cyber-glass-border">
                <div>Time</div>
                <div>Symbol</div>
                <div className="text-right">Side</div>
                <div className="text-right">Qty</div>
                <div className="text-right">Price</div>
                <div className="text-right">Fee</div>
                <div className="text-right">PnL</div>
                <div className="text-right">ID</div>
            </div>

            {/* Virtualized Rows */}
            <div ref={parentRef} className="flex-1 overflow-auto">
                <div
                    style={{
                        height: `${rowVirtualizer.getTotalSize()}px`,
                        width: '100%',
                        position: 'relative',
                    }}
                >
                    {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                        const trade = trades[virtualRow.index];
                        const isPnlPositive = trade.pnl > 0;

                        return (
                            <div
                                key={virtualRow.key}
                                style={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    width: '100%',
                                    height: `${virtualRow.size}px`,
                                    transform: `translateY(${virtualRow.start}px)`,
                                }}
                                className={cn(
                                    'grid grid-cols-8 gap-2 px-4 items-center',
                                    'text-xs font-mono',
                                    'border-b border-cyber-glass-border/30',
                                    'hover:bg-cyber-glass-bg transition-colors'
                                )}
                            >
                                <div className="text-cyber-text-dim">
                                    {new Date(trade.timestamp).toLocaleTimeString()}
                                </div>
                                <div className="text-cyber-text font-semibold">{trade.symbol}</div>
                                <div className={cn('text-right', trade.side === 'BUY' ? 'cyber-positive' : 'cyber-negative')}>
                                    {trade.side}
                                </div>
                                <div className="text-right text-cyber-text">{trade.quantity.toFixed(4)}</div>
                                <div className="text-right text-cyber-text">${trade.price.toFixed(2)}</div>
                                <div className="text-right text-cyber-negative">${trade.fee.toFixed(2)}</div>
                                <div className={cn('text-right font-semibold', isPnlPositive ? 'cyber-positive' : 'cyber-negative')}>
                                    {isPnlPositive ? '+' : ''}${trade.pnl.toFixed(2)}
                                </div>
                                <div className="text-right text-cyber-text-dim truncate">{trade.id.slice(0, 8)}</div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
