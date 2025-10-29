import { useNautilus } from '../state/store'

export default function SideNav() {
  const pods = useNautilus(s => s.pods)
  const watchlists = useNautilus(s => s.watchlists)

  return (
    <aside className="card p-3 space-y-3 w-full">
      <section>
        <div className="text-xs uppercase tracking-wide text-text-secondary mb-2">Strategy</div>
        <ul className="space-y-2">
          {pods.map(pod => (
            <li
              key={pod.id}
              className="flex items-center justify-between px-2 py-1.5 rounded bg-white/5 border border-white/10"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    pod.status === 'ok'
                      ? 'bg-emerald-400'
                      : pod.status === 'cooldown'
                      ? 'bg-amber-300'
                      : 'bg-red-500'
                  }`}
                />
                <span className="text-sm">{pod.name}</span>
              </div>
              <span className={pod.pnlPct >= 0 ? 'text-green-400 text-xs' : 'text-red-400 text-xs'}>
                {pod.pnlPct.toFixed(2)}%
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <div className="text-xs uppercase tracking-wide text-text-secondary mb-2">Watchlists</div>
        <div className="space-y-2">
          {watchlists.map(list => (
            <button
              key={list.id}
              className="w-full px-2 py-1.5 rounded bg-white/5 border border-white/10 text-left text-sm hover:bg-white/10 transition"
            >
              {list.name}
            </button>
          ))}
        </div>
      </section>
    </aside>
  )
}
