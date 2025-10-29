import { useMemo } from 'react'
import { useNautilus } from '../state/store'
import SymbolCard from './SymbolCard'

export default function SymbolGrid() {
  const symbols = useNautilus(s => s.symbols)

  const cards = useMemo(
    () =>
      symbols.map(sym => ({
        snapshot: sym,
        series: sym.series.map((y, idx) => ({ x: idx, y })),
      })),
    [symbols],
  )

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
      {cards.map(card => (
        <SymbolCard key={card.snapshot.id} snapshot={card.snapshot} series={card.series} />
      ))}
    </section>
  )
}
