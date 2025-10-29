import { create } from 'zustand'

export type Venue = 'Spot' | 'Margin' | 'Futures' | 'Options'

export interface StrategyPod {
  id: string
  name: string
  venue: Venue[]
  enabled: boolean
  allocationPct: number
  pnlPct: number
  latencyMs: number
  hitRate: number
  symbols: string[]
  status: 'ok' | 'cooldown' | 'error'
}

export interface SystemStatus {
  tradingEnabled: boolean
  mode: 'Paper' | 'Live'
  venuesEnabled: Record<Venue, boolean>
  portfolioEquity: number
  totalPnl: number
  dailyPnlPct: number
  sharpe: number
  maxDrawdownPct: number
  latencyMsP95: number
  signalPerMin: number
}

interface NautilusState {
  system: SystemStatus
  pods: StrategyPod[]
  toggleTrading(): void
  toggleMode(): void
  toggleVenue(v: Venue): void
  setAllocation(id: string, pct: number): void
  tick(): void
}

function range(n: number) { return [...Array(n).keys()] }

const initialPods: StrategyPod[] = [
  { id:'hmm-bin-fut', name:'HMM', venue:['Futures'], enabled:true, allocationPct:30, pnlPct: +1.8, latencyMs:28, hitRate:62, symbols:['BTC','ETH','SOL'], status:'ok' },
  { id:'meanrev-ibkr-eq', name:'MeanRev', venue:['Spot'], enabled:true, allocationPct:20, pnlPct: +2.2, latencyMs:31, hitRate:58, symbols:['AAPL','NVDA','MSFT'], status:'ok' },
  { id:'breakout-bin-spot', name:'Breakout', venue:['Spot'], enabled:true, allocationPct:25, pnlPct: +5.6, latencyMs:24, hitRate:54, symbols:['SOL','DOGE','OP'], status:'ok' },
  { id:'meme-detector', name:'Meme Pump', venue:['Spot'], enabled:false, allocationPct:5, pnlPct: +0.0, latencyMs:40, hitRate:35, symbols:['DOGE','PEPE'], status:'cooldown' },
  { id:'listing-sniper', name:'Listing Sniper', venue:['Spot','Futures'], enabled:false, allocationPct:5, pnlPct: +0.0, latencyMs:22, hitRate:0, symbols:[], status:'ok' }
]

export const useNautilus = create<NautilusState>((set, get) => ({
  system: {
    tradingEnabled: true,
    mode: 'Paper',
    venuesEnabled: { Spot:true, Margin:true, Futures:true, Options:false },
    portfolioEquity: 2000,
    totalPnl: 123.45,
    dailyPnlPct: 1.23,
    sharpe: 1.8,
    maxDrawdownPct: 6.4,
    latencyMsP95: 33,
    signalPerMin: 4.2,
  },
  pods: initialPods,
  toggleTrading() { set(s => ({ system: { ...s.system, tradingEnabled: !s.system.tradingEnabled } })) },
  toggleMode() { set(s => ({ system: { ...s.system, mode: s.system.mode === 'Paper' ? 'Live' : 'Paper' } })) },
  toggleVenue(v: Venue) {
    set(s => ({ system: { ...s.system, venuesEnabled: { ...s.system.venuesEnabled, [v]: !s.system.venuesEnabled[v] } } }))
  },
  setAllocation(id: string, pct: number) {
    set(s => ({ pods: s.pods.map(p => p.id===id ? { ...p, allocationPct: pct } : p) }))
  },
  tick() {
    // light mock updates to animate the UI in dev
    const s = get()
    const drift = (x:number)=> +(x + (Math.random()-0.5)*0.1).toFixed(2)
    set({
      system: {
        ...s.system,
        totalPnl: +(s.system.totalPnl + (Math.random()-0.5)*5).toFixed(2),
        dailyPnlPct: drift(s.system.dailyPnlPct),
        latencyMsP95: Math.max(10, Math.round(s.system.latencyMsP95 + (Math.random()-0.5)*2)),
        signalPerMin: Math.max(0, +(s.system.signalPerMin + (Math.random()-0.5)*0.2).toFixed(1)),
      },
      pods: s.pods.map(p => ({
        ...p,
        pnlPct: drift(p.pnlPct),
        latencyMs: Math.max(10, Math.round(p.latencyMs + (Math.random()-0.5)*3)),
        hitRate: Math.max(0, Math.min(100, Math.round(p.hitRate + (Math.random()-0.5)*2)))
      }))
    })
  }
}))

// auto-tick in dev (ssr-safe noop)
if (typeof window !== 'undefined') {
  setInterval(() => {
    try { useNautilus.getState().tick() } catch {}
  }, 2000)
}
