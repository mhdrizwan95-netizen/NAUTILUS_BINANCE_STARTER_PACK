import StrategyPod from './StrategyPod'
import { useNautilus } from '../state/store'

export default function StrategyMatrix() {
  const pods = useNautilus(s => s.pods)

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
      {pods.map(pod => (
        <StrategyPod key={pod.id} pod={pod} />
      ))}
    </section>
  )
}
