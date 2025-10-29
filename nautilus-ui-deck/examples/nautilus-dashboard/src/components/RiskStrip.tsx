import { useNautilus } from '../state/store'

export default function RiskStrip() {
  const risk = useNautilus(s => s.risk)

  const items = [
    { label: 'VAR', value: `${risk.varPct.toFixed(2)}%` },
    { label: 'Margin usage', value: `${risk.marginUsagePct.toFixed(1)}%` },
    { label: 'Drawdown', value: `${risk.drawdownPct.toFixed(1)}%` },
    { label: 'Alerts', value: risk.alerts.toString() },
  ]

  return (
    <div className="card p-2 flex flex-wrap items-center justify-between text-xs gap-3">
      {items.map(item => (
        <div key={item.label} className="flex items-center gap-2">
          <span className="text-text-secondary uppercase tracking-wide">{item.label}</span>
          <span className="font-mono">{item.value}</span>
        </div>
      ))}
    </div>
  )
}
