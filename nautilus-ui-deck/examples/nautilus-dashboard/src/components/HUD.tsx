import { useNautilus } from '../state/store'

export default function HUD() {
  const system = useNautilus(s => s.system)
  const toggleTrading = useNautilus(s => s.toggleTrading)
  const toggleMode = useNautilus(s => s.toggleMode)
  const toggleVenue = useNautilus(s => s.toggleVenue)

  return (
    <header className="card p-3 md:p-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="text-xl font-mono tracking-tight">NAUTILUS • Command Center</div>
        <span className={`px-2 py-0.5 rounded text-xs ${system.tradingEnabled ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
          {system.tradingEnabled ? 'TRADING: ON' : 'TRADING: OFF'}
        </span>
        <button onClick={toggleTrading} className="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-xs">Toggle</button>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-text-secondary text-xs">Mode</span>
          <button onClick={toggleMode} className="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-xs">
            {system.mode}
          </button>
        </div>

        <div className="hidden md:flex items-center gap-2">
          {(['Spot','Margin','Futures','Options'] as const).map(v => (
            <button key={v} onClick={() => toggleVenue(v)} className={`px-2 py-1 rounded text-xs border ${system.venuesEnabled[v] ? 'border-white/30 bg-white/10' : 'border-white/10 text-text-secondary'}`}>
              {v}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-4 text-sm">
          <span>NAV ${system.portfolioEquity.toFixed(2)}</span>
          <span className={`${system.dailyPnlPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>{system.dailyPnlPct.toFixed(2)}%</span>
          <span className="text-text-secondary">Sharpe {system.sharpe.toFixed(2)}</span>
          <span className="text-text-secondary">DD {system.maxDrawdownPct.toFixed(1)}%</span>
          <span className="text-text-secondary">p95 {system.latencyMsP95}ms</span>
        </div>
      </div>
    </header>
  )
}
