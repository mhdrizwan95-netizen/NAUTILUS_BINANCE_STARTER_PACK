import { useNautilus } from '../state/store'

export default function VenueHealth() {
  const venues = useNautilus(s => s.venueLatency)

  return (
    <div className="card p-2 flex flex-wrap items-center gap-3">
      {venues.map(venue => (
        <div
          key={venue.venue}
          className="px-2 py-1 rounded bg-white/5 border border-white/10 text-xs flex items-center gap-2"
        >
          <span className="text-text-secondary">{venue.venue}</span>
          <span className="font-mono">{venue.ms} ms</span>
          <span className={venue.up ? 'text-emerald-300' : 'text-rose-300'}>{venue.up ? '▲' : '▼'}</span>
        </div>
      ))}
    </div>
  )
}
