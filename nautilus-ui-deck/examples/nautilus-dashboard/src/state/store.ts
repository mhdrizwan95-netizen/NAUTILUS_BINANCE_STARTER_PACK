import { create } from 'zustand'

export type Venue = 'Spot' | 'Margin' | 'Futures' | 'Options'
export type Accent = 'crypto' | 'equity' | 'fx'

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

export interface Watchlist {
  id: string
  name: string
  symbols: string[]
}

export interface SymbolSnapshot {
  id: string
  symbol: string
  venue: string
  status: 'Live' | 'Active' | 'Inactive' | 'Error'
  changePct: number
  last: number
  accent: Accent
  series: number[]
}

export interface VenueLatency {
  venue: string
  ms: number
  up: boolean
}

export interface OrderBookSnapshot {
  symbol: string
  venue: string
  bids: { px: number; qty: number }[]
  asks: { px: number; qty: number }[]
}

export interface ExecutionEvent {
  ts: string
  symbol: string
  venue: string
  side: 'BUY' | 'SELL'
  price: number
  qty: number
  pnlPct?: number
}

export interface RiskSnapshot {
  varPct: number
  marginUsagePct: number
  drawdownPct: number
  alerts: number
}

export interface StrategyMetrics {
  confidence: number
  volatility: 'Low' | 'Medium' | 'High'
  position: 'Long' | 'Short' | 'Flat'
  varPct: number
}

interface NautilusState {
  system: SystemStatus
  pods: StrategyPod[]
  watchlists: Watchlist[]
  symbols: SymbolSnapshot[]
  venueLatency: VenueLatency[]
  orderBook: OrderBookSnapshot
  executionFeed: ExecutionEvent[]
  risk: RiskSnapshot
  strategyMetrics: StrategyMetrics
  toggleTrading(): void
  toggleMode(): void
  toggleVenue(v: Venue): void
  setAllocation(id: string, pct: number): void
  tick(): void
}

const initialPods: StrategyPod[] = [
  { id:'hmm-bin-fut', name:'HMM', venue:['Futures'], enabled:true, allocationPct:30, pnlPct:+1.8, latencyMs:28, hitRate:62, symbols:['BTC','ETH','SOL'], status:'ok' },
  { id:'meanrev-ibkr-eq', name:'MeanRev', venue:['Spot'], enabled:true, allocationPct:20, pnlPct:+2.2, latencyMs:31, hitRate:58, symbols:['AAPL','NVDA','MSFT'], status:'ok' },
  { id:'breakout-bin-spot', name:'Breakout', venue:['Spot'], enabled:true, allocationPct:25, pnlPct:+5.6, latencyMs:24, hitRate:54, symbols:['SOL','DOGE','OP'], status:'ok' },
  { id:'meme-detector', name:'Meme Pump', venue:['Spot'], enabled:false, allocationPct:5, pnlPct:+0.0, latencyMs:40, hitRate:35, symbols:['DOGE','PEPE'], status:'cooldown' },
  { id:'listing-sniper', name:'Listing Sniper', venue:['Spot','Futures'], enabled:false, allocationPct:5, pnlPct:+0.0, latencyMs:22, hitRate:0, symbols:[], status:'ok' },
]

const watchlists: Watchlist[] = [
  { id:'core', name:'HMM Core', symbols:['BTC','ETH','SOL'] },
  { id:'majors', name:'Majors', symbols:['BTCUSDT','ETHUSDT','DOGEUSDT'] },
  { id:'equities', name:'US Equities', symbols:['AAPL','NVDA','MSFT'] },
]

const spark = (base: number) =>
  Array.from({ length: 24 }, (_, i) =>
    +(base + Math.sin((i + base / 100) / 3) * 1.6 + (Math.random() - 0.5) * 0.9).toFixed(2)
  )

const initialSymbols: SymbolSnapshot[] = [
  { id:'btc-binance', symbol:'BTCUSDT', venue:'Binance', status:'Live', changePct:1.32, last:27415, accent:'crypto', series: spark(27400) },
  { id:'eth-bybit', symbol:'ETHUSDT', venue:'Bybit', status:'Active', changePct:-0.63, last:1810, accent:'crypto', series: spark(1810) },
  { id:'aapl-ibkr', symbol:'AAPL', venue:'IBKR', status:'Error', changePct:0.48, last:166.07, accent:'equity', series: spark(166) },
  { id:'usdkraken', symbol:'USDJPY', venue:'Kraken', status:'Live', changePct:0.72, last:146.25, accent:'fx', series: spark(146) },
  { id:'sol-binance', symbol:'SOLUSDT', venue:'Binance', status:'Active', changePct:1.12, last:32.4, accent:'crypto', series: spark(32) },
  { id:'msft-ibkr', symbol:'MSFT', venue:'IBKR', status:'Inactive', changePct:-0.28, last:312.33, accent:'equity', series: spark(312) },
]

const initialVenueLatency: VenueLatency[] = [
  { venue: 'Binance', ms: 12, up: true },
  { venue: 'Bybit', ms: 17, up: true },
  { venue: 'IBKR', ms: 34, up: false },
  { venue: 'Kraken', ms: 20, up: true },
]

const initialOrderBook: OrderBookSnapshot = {
  symbol: 'BTCUSDT',
  venue: 'Binance',
  bids: [
    { px: 27418, qty: 3.2 },
    { px: 27417, qty: 2.2 },
    { px: 27415, qty: 1.9 },
  ],
  asks: [
    { px: 27419, qty: 2.1 },
    { px: 27420, qty: 3.6 },
    { px: 27422, qty: 3.3 },
  ],
}

const initialExecutionFeed: ExecutionEvent[] = [
  { ts:'12:01:23', symbol:'BTCUSDT', venue:'Binance', side:'BUY', price:27418, qty:0.02 },
  { ts:'12:03:10', symbol:'BTCUSDT', venue:'Binance', side:'SELL', price:27465, qty:0.02, pnlPct:+0.9 },
  { ts:'12:05:33', symbol:'ETHUSDT', venue:'Bybit', side:'BUY', price:1811, qty:0.5 },
]

const initialRisk: RiskSnapshot = { varPct:1.6, marginUsagePct:14, drawdownPct:3.1, alerts:1 }
const initialStrategyMetrics: StrategyMetrics = { confidence:0.72, volatility:'High', position:'Long', varPct:1.6 }

const formatTime = () =>
  new Date().toLocaleTimeString('en-US', { hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit' })

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
  watchlists,
  symbols: initialSymbols,
  venueLatency: initialVenueLatency,
  orderBook: initialOrderBook,
  executionFeed: initialExecutionFeed,
  risk: initialRisk,
  strategyMetrics: initialStrategyMetrics,
  toggleTrading() { set(s => ({ system: { ...s.system, tradingEnabled: !s.system.tradingEnabled } })) },
  toggleMode() { set(s => ({ system: { ...s.system, mode: s.system.mode === 'Paper' ? 'Live' : 'Paper' } })) },
  toggleVenue(v: Venue) {
    set(s => ({ system: { ...s.system, venuesEnabled: { ...s.system.venuesEnabled, [v]: !s.system.venuesEnabled[v] } } }))
  },
  setAllocation(id: string, pct: number) {
    set(s => ({ pods: s.pods.map(p => p.id===id ? { ...p, allocationPct: pct } : p) }))
  },
  tick() {
    const state = get()
    const drift = (x:number)=> +(x + (Math.random()-0.5)*0.1).toFixed(2)

    const symbols = state.symbols.map(sym => {
      const last = sym.series[sym.series.length - 1]
      const nextLast = +(last + (Math.random() - 0.5) * Math.max(1, sym.last * 0.004)).toFixed(2)
      const nextSeries = [...sym.series.slice(1), nextLast]
      const base = nextSeries[0] === 0 ? 1 : nextSeries[0]
      const changePct = +(((nextLast - base) / base) * 100).toFixed(2)
      return { ...sym, series: nextSeries, last: nextLast, changePct }
    })

    const venueLatency = state.venueLatency.map(v => {
      const ms = Math.max(8, Math.round(v.ms + (Math.random() - 0.5) * 3))
      const up = Math.random() > 0.2 ? true : ms < v.ms
      return { ...v, ms, up }
    })

    const mid = symbols[0]?.series.at(-1) ?? state.orderBook.bids[0].px
    const orderBook: OrderBookSnapshot = {
      symbol: symbols[0]?.symbol ?? state.orderBook.symbol,
      venue: symbols[0]?.venue ?? state.orderBook.venue,
      bids: Array.from({ length: 3 }).map((_, idx) => ({
        px: +(mid - (idx + 1) * 1).toFixed(2),
        qty: +(Math.random() * 2.5 + 1).toFixed(2),
      })),
      asks: Array.from({ length: 3 }).map((_, idx) => ({
        px: +(mid + (idx + 1) * 1).toFixed(2),
        qty: +(Math.random() * 2.5 + 1).toFixed(2),
      })),
    }

    let executionFeed = state.executionFeed
    if (Math.random() > 0.6) {
      const side = Math.random() > 0.5 ? 'BUY' : 'SELL'
      const price = +(mid + (Math.random() - 0.5) * 5).toFixed(2)
      const qty = +(Math.random() * 0.05 + 0.01).toFixed(3)
      const pnlPct = side === 'SELL' ? +(Math.random() * 1.2).toFixed(2) : undefined
      const evt: ExecutionEvent = {
        ts: formatTime(),
        symbol: symbols[0]?.symbol ?? 'BTCUSDT',
        venue: symbols[0]?.venue ?? 'Binance',
        side,
        price,
        qty,
        pnlPct,
      }
      executionFeed = [evt, ...executionFeed].slice(0, 6)
    }

    const risk: RiskSnapshot = {
      varPct: drift(state.risk.varPct),
      marginUsagePct: +(state.risk.marginUsagePct + (Math.random() - 0.5) * 0.8).toFixed(1),
      drawdownPct: +(state.risk.drawdownPct + (Math.random() - 0.5) * 0.4).toFixed(1),
      alerts: Math.max(0, state.risk.alerts + (Math.random() > 0.92 ? 1 : 0)),
    }

    const strategyMetrics: StrategyMetrics = {
      confidence: Math.min(1, Math.max(0, drift(state.strategyMetrics.confidence))),
      volatility: state.strategyMetrics.volatility,
      position: Math.random() > 0.6 ? 'Long' : Math.random() > 0.5 ? 'Short' : 'Flat',
      varPct: drift(state.strategyMetrics.varPct),
    }

    set({
      system: {
        ...state.system,
        totalPnl: +(state.system.totalPnl + (Math.random()-0.5)*5).toFixed(2),
        dailyPnlPct: drift(state.system.dailyPnlPct),
        latencyMsP95: Math.max(10, Math.round(state.system.latencyMsP95 + (Math.random()-0.5)*2)),
        signalPerMin: Math.max(0, +(state.system.signalPerMin + (Math.random()-0.5)*0.2).toFixed(1)),
      },
      pods: state.pods.map(p => ({
        ...p,
        pnlPct: drift(p.pnlPct),
        latencyMs: Math.max(10, Math.round(p.latencyMs + (Math.random()-0.5)*3)),
        hitRate: Math.max(0, Math.min(100, Math.round(p.hitRate + (Math.random()-0.5)*2))),
      })),
      symbols,
      venueLatency,
      orderBook,
      executionFeed,
      risk,
      strategyMetrics,
    })
  },
}))

if (typeof window !== 'undefined') {
  setInterval(() => {
    try { useNautilus.getState().tick() } catch {}
  }, 2000)
}
