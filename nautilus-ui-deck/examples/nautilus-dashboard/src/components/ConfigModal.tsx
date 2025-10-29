import { useState } from 'react'

type Props = {
  title: string
  onClose: () => void
}

export default function ConfigModal({ title, onClose }: Props) {
  const [params, setParams] = useState({
    maShort: 20,
    maLong: 100,
    rsiBuy: 55,
    trailingStop: 2.0,
    maxConcurrent: 5
  })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 grid place-items-center p-4">
      <div className="card w-full max-w-md p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold">{title} — Config</h3>
          <button onClick={onClose} className="text-sm text-text-secondary hover:text-white">Close</button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <label className="space-y-1">
            <div className="text-text-secondary text-xs">MA Short</div>
            <input type="number" value={params.maShort} onChange={e=>setParams({ ...params, maShort:+e.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded px-2 py-1" />
          </label>
          <label className="space-y-1">
            <div className="text-text-secondary text-xs">MA Long</div>
            <input type="number" value={params.maLong} onChange={e=>setParams({ ...params, maLong:+e.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded px-2 py-1" />
          </label>
          <label className="space-y-1">
            <div className="text-text-secondary text-xs">RSI Buy</div>
            <input type="number" value={params.rsiBuy} onChange={e=>setParams({ ...params, rsiBuy:+e.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded px-2 py-1" />
          </label>
          <label className="space-y-1">
            <div className="text-text-secondary text-xs">Trailing Stop %</div>
            <input type="number" step="0.1" value={params.trailingStop} onChange={e=>setParams({ ...params, trailingStop:+e.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded px-2 py-1" />
          </label>
          <label className="space-y-1 col-span-2">
            <div className="text-text-secondary text-xs">Max Concurrent Trades</div>
            <input type="number" value={params.maxConcurrent} onChange={e=>setParams({ ...params, maxConcurrent:+e.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded px-2 py-1" />
          </label>
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1 rounded bg-white/10 hover:bg-white/20">Cancel</button>
          <button onClick={onClose} className="px-3 py-1 rounded bg-white text-black">Save</button>
        </div>
      </div>
    </div>
  )
}
