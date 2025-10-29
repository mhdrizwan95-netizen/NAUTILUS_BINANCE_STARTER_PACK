import { LineChart, Line, ResponsiveContainer } from 'recharts'
import type { SymbolSnapshot } from '../state/store'

export type SymbolCardData = {
  snapshot: SymbolSnapshot
  series: { x: number; y: number }[]
}

export default function SymbolCard({ snapshot, series }: SymbolCardData) {
  const accentClass =
    snapshot.accent === 'equity'
      ? 'text-amber-300'
      : snapshot.accent === 'fx'
      ? 'text-violet-300'
      : 'text-teal-300'

  const stroke =
    snapshot.accent === 'equity'
      ? '#FFB400'
      : snapshot.accent === 'fx'
      ? '#8C6FF0'
      : '#00C2BA'

  const pillClass =
    snapshot.status === 'Live'
      ? 'bg-emerald-500/15 text-emerald-300'
      : snapshot.status === 'Error'
      ? 'bg-red-500/15 text-red-300'
      : 'bg-white/10 text-text-secondary'

  return (
    <div className="card p-3">
      <div className="flex items-center justify-between text-sm">
        <div className="font-medium">{snapshot.symbol}</div>
        <div className="text-text-secondary">{snapshot.venue}</div>
      </div>
      <div className="h-16 my-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series}>
            <Line type="monotone" dataKey="y" dot={false} stroke={stroke} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className={snapshot.changePct >= 0 ? 'text-green-400' : 'text-red-400'}>
          {snapshot.changePct.toFixed(2)}%
        </span>
        <span className={`font-mono ${accentClass}`}>{snapshot.last.toLocaleString()}</span>
        <span className={`px-1.5 py-0.5 rounded text-xs ${pillClass}`}>{snapshot.status}</span>
      </div>
    </div>
  )
}
