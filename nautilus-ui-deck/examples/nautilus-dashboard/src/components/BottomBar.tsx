import { useNautilus } from '../state/store'

export default function BottomBar() {
  const system = useNautilus(s => s.system)
  return (
    <footer className="card p-2 flex items-center justify-between text-xs mt-2">
      <div className="flex items-center gap-3">
        <span className="text-text-secondary">API</span>
        <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-400">Connected</span>
        <span className="text-text-secondary">Mode:</span>
        <span>{system.mode}</span>
      </div>
      <div className="text-text-secondary">
        Last tick just now • Uptime 12h 03m
      </div>
    </footer>
  )
}
