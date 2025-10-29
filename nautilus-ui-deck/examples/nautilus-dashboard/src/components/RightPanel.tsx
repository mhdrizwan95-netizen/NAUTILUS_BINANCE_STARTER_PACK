import { useNautilus } from '../state/store'
import { LineChart, Line, Tooltip, ResponsiveContainer } from 'recharts'
import { useMemo } from 'react'

export default function RightPanel() {
  const system = useNautilus(s => s.system)
  const pods = useNautilus(s => s.pods)

  const series = useMemo(() => {
    // fabricate a small series around current values for placeholder sparkline
    const base = system.totalPnl
    return Array.from({length: 24}).map((_,i)=>({ x:i, y: +(base + Math.sin(i/3)*10 + (Math.random()-0.5)*5).toFixed(2) }))
  }, [system.totalPnl])

  return (
    <aside className="card p-3 md:p-4 w-full md:w-[360px]">
      <div className="font-semibold mb-2">Performance</div>
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series}>
            <Line type="monotone" dataKey="y" dot={false} strokeWidth={2} />
            <Tooltip />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm mt-3">
        <div>Total PnL <span className={system.totalPnl>=0?'text-green-400':'text-red-400'}>${system.totalPnl.toFixed(2)}</span></div>
        <div>Signals/min <span className="text-text-secondary">{system.signalPerMin}</span></div>
        <div>Sharpe <span className="text-text-secondary">{system.sharpe.toFixed(2)}</span></div>
        <div>Max DD <span className="text-text-secondary">{system.maxDrawdownPct.toFixed(1)}%</span></div>
      </div>

      <div className="mt-4">
        <div className="text-xs text-text-secondary mb-1">By Strategy</div>
        <ul className="space-y-1 text-sm">
          {pods.map(p => (
            <li key={p.id} className="flex items-center justify-between">
              <span>{p.name}</span>
              <span className={p.pnlPct>=0?'text-green-400':'text-red-400'}>{p.pnlPct.toFixed(2)}%</span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  )
}
