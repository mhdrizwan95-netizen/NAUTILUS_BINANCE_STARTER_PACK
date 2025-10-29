import { useNautilus } from '../state/store'

export default function StrategyMetricsCard() {
  const metrics = useNautilus(s => s.strategyMetrics)

  return (
    <div className="card p-3 text-sm">
      <div className="font-medium mb-2">Strategy Metrics</div>
      <div className="grid grid-cols-2 gap-2">
        <div className="text-text-secondary">Confidence</div>
        <div className="font-mono">{(metrics.confidence * 100).toFixed(1)}%</div>

        <div className="text-text-secondary">Volatility</div>
        <div className="text-amber-300">{metrics.volatility}</div>

        <div className="text-text-secondary">Position</div>
        <div className={metrics.position === 'Long' ? 'text-emerald-300' : metrics.position === 'Short' ? 'text-rose-300' : ''}>
          {metrics.position}
        </div>

        <div className="text-text-secondary">VAR</div>
        <div>{metrics.varPct.toFixed(2)}%</div>
      </div>
    </div>
  )
}
