import { useNautilus } from '../state/store'

export default function OrderBookPanel() {
  const orderBook = useNautilus(s => s.orderBook)

  if (!orderBook) {
    return null
  }

  const spread =
    orderBook.asks.length && orderBook.bids.length
      ? (orderBook.asks[0].px - orderBook.bids[0].px).toFixed(2)
      : '—'

  return (
    <div className="card p-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{orderBook.symbol}</div>
        <div className="text-text-secondary text-xs">{orderBook.venue} • Live</div>
      </div>

      <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
        <div>
          <div className="text-text-secondary text-xs mb-1">Bids</div>
          <ul className="space-y-1">
            {orderBook.bids.map((level, idx) => (
              <li key={idx} className="flex justify-between bg-emerald-500/5 px-2 py-1 rounded">
                <span>{level.px.toLocaleString()}</span>
                <span className="text-emerald-300">{level.qty.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-text-secondary text-xs mb-1">Asks</div>
          <ul className="space-y-1">
            {orderBook.asks.map((level, idx) => (
              <li key={idx} className="flex justify-between bg-rose-500/5 px-2 py-1 rounded">
                <span>{level.px.toLocaleString()}</span>
                <span className="text-rose-300">{level.qty.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-2 text-xs text-text-secondary">Spread: {spread}</div>
    </div>
  )
}
