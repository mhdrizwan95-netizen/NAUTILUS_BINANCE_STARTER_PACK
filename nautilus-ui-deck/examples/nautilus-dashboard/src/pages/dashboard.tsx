import HUD from '../components/HUD'
import SideNav from '../components/SideNav'
import SymbolGrid from '../components/SymbolGrid'
import StrategyMatrix from '../components/StrategyMatrix'
import OrderBookPanel from '../components/OrderBookPanel'
import StrategyMetricsCard from '../components/StrategyMetricsCard'
import ExecutionFeed from '../components/ExecutionFeed'
import VenueHealth from '../components/VenueHealth'
import RiskStrip from '../components/RiskStrip'

export default function Dashboard() {
  return (
    <main className="min-h-screen p-3 md:p-4 space-y-3">
      <HUD />

      <VenueHealth />

      <section className="grid grid-cols-1 md:grid-cols-12 gap-3">
        <div className="md:col-span-3 space-y-3">
          <SideNav />
        </div>

        <div className="md:col-span-6 space-y-3">
          <SymbolGrid />
          <StrategyMatrix />
        </div>

        <div className="md:col-span-3 space-y-3">
          <OrderBookPanel />
          <StrategyMetricsCard />
          <ExecutionFeed />
        </div>
      </section>

      <RiskStrip />
    </main>
  )
}
