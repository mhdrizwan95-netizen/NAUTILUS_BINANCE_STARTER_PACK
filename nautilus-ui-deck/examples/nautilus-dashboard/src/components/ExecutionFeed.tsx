import { useNautilus } from '../state/store'

export default function ExecutionFeed() {
  const feed = useNautilus(s => s.executionFeed)

  return (
    <div className="card p-3 text-sm">
      <div className="font-medium mb-2">Execution Feed</div>
      <ul className="space-y-1">
        {feed.map((event, idx) => (
          <li
            key={`${event.ts}-${idx}`}
            className="flex items-center justify-between px-2 py-1 rounded bg-white/5 border border-white/10"
          >
            <span className="text-text-secondary">{event.ts}</span>
            <span>{event.symbol}</span>
            <span className={event.side === 'BUY' ? 'text-emerald-300' : 'text-rose-300'}>{event.side}</span>
            <span className="font-mono">{event.price.toLocaleString()}</span>
            <span className="text-text-secondary">{event.qty}</span>
            {event.pnlPct !== undefined && (
              <span className={event.pnlPct >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                {event.pnlPct > 0 ? '+' : ''}
                {event.pnlPct.toFixed(2)}%
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
