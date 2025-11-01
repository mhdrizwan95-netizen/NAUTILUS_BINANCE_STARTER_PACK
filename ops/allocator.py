# ops/allocator.py
from prometheus_client import Gauge

# exported knobs (match your import line)
TOTAL_ALLOC_USD = 1000.0
ALLOC_ALPHA = 0.3
ALLOC_BETA = 0.2
ALLOC_SMOOTH = 0.5

alloc_weight_g = Gauge("alloc_weight", "Normalized weight per model", ["model"])
alloc_usd_g = Gauge("alloc_usd", "Allocated USD per model", ["model"])


class Allocator:
    def __init__(
        self,
        total_usd: float = TOTAL_ALLOC_USD,
        alpha: float = ALLOC_ALPHA,
        beta: float = ALLOC_BETA,
        smooth: float = ALLOC_SMOOTH,
    ):
        self.total_usd = total_usd
        self.alpha, self.beta, self.smooth = alpha, beta, smooth
        self.weights = {}

    def update(self, perf: dict) -> dict:
        # trivial pass-through until you wire real scoring:
        # assign equal weights to all keys in perf; default single bucket
        keys = list(perf.keys()) or ["default"]
        w = 1.0 / len(keys)
        for k in keys:
            self.weights[k] = w
            alloc = w * self.total_usd
            alloc_weight_g.labels(model=k).set(w)
            alloc_usd_g.labels(model=k).set(alloc)
        return self.weights

    def get_tactic_allocation(self, tactic: str, base_size: float) -> float:
        """Get the adjusted size for a tactic. Default to base_size."""
        return base_size  # Stub: always return base size, no scaling yet
