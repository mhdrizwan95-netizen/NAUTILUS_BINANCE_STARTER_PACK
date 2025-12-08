import { create } from 'zustand';

interface SimpleState {
    portfolio: { equity: number; margin_level?: number };
    trades: any[];
}

export const useSimpleStore = create<SimpleState>((set) => ({
    portfolio: { equity: 10000, margin_level: 0.5 },
    trades: [],
}));

export const useSimplePortfolio = () => useSimpleStore((state) => state.portfolio);
export const useSimpleTrades = () => useSimpleStore((state) => state.trades);
