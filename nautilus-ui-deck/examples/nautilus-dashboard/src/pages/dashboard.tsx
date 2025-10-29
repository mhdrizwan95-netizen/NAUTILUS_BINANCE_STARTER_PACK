import HUD from '../components/HUD'
import StrategyPod from '../components/StrategyPod'
import RightPanel from '../components/RightPanel'
import BottomBar from '../components/BottomBar'
import { useNautilus } from '../state/store'

export default function Dashboard() {
  const pods = useNautilus(s => s.pods)

  return (
    <main className="min-h-screen p-3 md:p-4 space-y-3">
      <HUD />

      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="md:col-span-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {pods.map(p => <StrategyPod key={p.id} pod={p} />)}
        </div>
        <RightPanel />
      </section>

      <BottomBar />
    </main>
  )
}
