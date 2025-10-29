import { useState } from 'react'
import { motion } from 'framer-motion'
import { StrategyPod as Pod, useNautilus } from '../state/store'
import ConfigModal from './ConfigModal'

export default function StrategyPod({ pod }: { pod: Pod }) {
  const setAllocation = useNautilus(s => s.setAllocation)
  const [open, setOpen] = useState(false)

  const rim = pod.status === 'error' ? 'ring-2 ring-red-500/60' : pod.status === 'cooldown' ? 'opacity-60' : ''
  const MotionDiv = motion.div as any

  return (
    <MotionDiv whileHover={{ y: -2 }} className={`card p-3 ${rim}`}>
      <div className="flex items-center justify-between">
        <div className="font-semibold">{pod.name}</div>
        <div className="flex items-center gap-1 text-xs text-text-secondary">
          {pod.venue.map(v => <span key={v} className="px-1 py-0.5 rounded bg-white/5 border border-white/10">{v}</span>)}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2 text-sm">
        <div> PnL <span className={pod.pnlPct>=0 ? 'text-green-400' : 'text-red-400'}>{pod.pnlPct.toFixed(2)}%</span></div>
        <div> HitRate <span className="text-text-secondary">{pod.hitRate}%</span></div>
        <div> Latency <span className="text-text-secondary">{pod.latencyMs}ms</span></div>
        <div> Symbols <span className="text-text-secondary">{pod.symbols.join(', ') || '—'}</span></div>
      </div>

      <div className="mt-3">
        <label className="text-xs text-text-secondary">Allocation {pod.allocationPct}%</label>
        <input type="range" min={0} max={100} value={pod.allocationPct}
          onChange={(e)=> setAllocation(pod.id, +e.target.value)}
          className="w-full accent-white" />
      </div>

      <div className="mt-2 flex items-center justify-between text-xs">
        <button className="px-2 py-1 rounded bg-white/10 hover:bg-white/20" onClick={()=>setOpen(true)}>Config</button>
        <div className="text-text-secondary">Status: {pod.status}</div>
      </div>

      {open && <ConfigModal title={pod.name} onClose={()=>setOpen(false)} />}
    </MotionDiv>
  )
}
