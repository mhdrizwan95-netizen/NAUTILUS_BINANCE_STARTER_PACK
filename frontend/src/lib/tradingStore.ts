/**
 * High-Performance Zustand Store
 * 
 * Uses selector-based subscriptions to prevent full tree re-renders.
 * Designed to handle 100+ price ticks/sec without UI stutter.
 */
import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';

// Types
export interface PriceTick {
    symbol: string;
    price: number;
    volume: number;
    timestamp: number;
}

export interface Position {
    symbol: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    avgPrice: number;
    unrealizedPnl: number;
    marketValue: number;
}

export interface Trade {
    id: string;
    symbol: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    price: number;
    fee: number;
    pnl: number;
    timestamp: number;
}

export interface Portfolio {
    equity: number;
    cash: number;
    balances: Record<string, number>; // Multi-currency
    realizedPnl: number;
    unrealizedPnl: number;
    fees: number;
    positions: Position[];
}

export interface StrategyStatus {
    name: string;
    enabled: boolean;
    confidence: number;
    signal: number; // -1 to 1
    lastUpdate: number;
}

export interface VenueHealth {
    name: string;
    connected: boolean;
    latencyMs: number;
    queue: number;
    wsGapSeconds: number; // Heartbeat monitor
}

export interface SystemHealth {
    tradingEnabled: boolean;
    circuitBreakerTripped: boolean;
    cpuPercent?: number;
    memoryMb?: number;
    rateLimitUsage?: number; // 0-100%
}

// Store State
interface TradingState {
    // High-frequency data (updated on every tick)
    prices: Map<string, PriceTick>;

    // Medium-frequency data (updated on fills/updates)
    portfolio: Portfolio;
    trades: Trade[];
    strategies: Map<string, StrategyStatus>;

    // Low-frequency data (updated periodically)
    venues: Map<string, VenueHealth>;
    health: SystemHealth;

    // Actions
    updatePrice: (tick: PriceTick) => void;
    updatePrices: (ticks: PriceTick[]) => void; // Batch update
    setPortfolio: (portfolio: Portfolio) => void;
    addTrade: (trade: Trade) => void;
    updateStrategy: (name: string, status: Partial<StrategyStatus>) => void;
    updateVenue: (name: string, health: VenueHealth) => void;
    setSystemHealth: (health: Partial<SystemHealth>) => void;
}

// Create store with middleware
export const useTradingStore = create<TradingState>()(
    devtools(
        subscribeWithSelector((set) => ({
            // Initial state
            prices: new Map(),
            portfolio: {
                equity: 0,
                cash: 0,
                balances: {},
                realizedPnl: 0,
                unrealizedPnl: 0,
                fees: 0,
                positions: [],
            },
            trades: [],
            strategies: new Map([
                ['HMM_Trend_v2', { name: 'HMM_Trend_v2', enabled: true, confidence: 0.85, signal: 1, lastUpdate: Date.now() }],
                ['MeanRev_Scalp', { name: 'MeanRev_Scalp', enabled: true, confidence: 0.65, signal: -0.5, lastUpdate: Date.now() }],
                ['Meme_Sniper', { name: 'Meme_Sniper', enabled: false, confidence: 0.1, signal: 0, lastUpdate: Date.now() }],
            ]),
            venues: new Map(),
            health: {
                tradingEnabled: false,
                circuitBreakerTripped: false,
            },

            // High-performance actions
            updatePrice: (tick) =>
                set((state) => {
                    const newPrices = new Map(state.prices);
                    newPrices.set(tick.symbol, tick);
                    return { prices: newPrices };
                }),

            updatePrices: (ticks) =>
                set((state) => {
                    const newPrices = new Map(state.prices);
                    ticks.forEach((tick) => newPrices.set(tick.symbol, tick));
                    return { prices: newPrices };
                }),

            setPortfolio: (portfolio) => set({ portfolio }),

            addTrade: (trade) =>
                set((state) => ({
                    trades: [trade, ...state.trades].slice(0, 1000), // Keep last 1000
                })),

            updateStrategy: (name, status) =>
                set((state) => {
                    const newStrategies = new Map(state.strategies);
                    const existing = newStrategies.get(name) || {
                        name,
                        enabled: false,
                        confidence: 0,
                        signal: 0,
                        lastUpdate: Date.now(),
                    };
                    newStrategies.set(name, { ...existing, ...status, lastUpdate: Date.now() });
                    return { strategies: newStrategies };
                }),

            updateVenue: (name, health) =>
                set((state) => {
                    const newVenues = new Map(state.venues);
                    newVenues.set(name, health);
                    return { venues: newVenues };
                }),

            setSystemHealth: (health) =>
                set((state) => ({
                    health: { ...state.health, ...health },
                })),
        })),
        { name: 'TradingStore' }
    )
);

// Selector hooks (memoized - prevents unnecessary re-renders)
export const usePrice = (symbol: string) =>
    useTradingStore((state) => state.prices.get(symbol));

export const usePortfolio = () => useTradingStore((state) => state.portfolio);

export const useRecentTrades = (limit: number = 100) =>
    useTradingStore((state) => state.trades.slice(0, limit));

export const useStrategy = (name: string) =>
    useTradingStore((state) => state.strategies.get(name));

export const useAllStrategies = () =>
    useTradingStore((state) => Array.from(state.strategies.values()));

export const useVenue = (name: string) =>
    useTradingStore((state) => state.venues.get(name));

export const useSystemHealth = () => useTradingStore((state) => state.health);

// Derived selectors (computed)
export const useTotalPnl = () =>
    useTradingStore((state) => state.portfolio.realizedPnl + state.portfolio.unrealizedPnl);

export const useIsConnected = () =>
    useTradingStore((state) => Array.from(state.venues.values()).some((v) => v.connected));
