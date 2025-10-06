# M4: strategy.py (skeleton for Nautilus Strategy subclass)
# NOTE: This is a placeholder to guide Cline. Replace hooks with actual Nautilus API methods.
from .config import HMMPolicyConfig
from .features import FeatureState, compute_features
from .policy import decide_action
from .guardrails import check_gates, Block

class HMMPolicyStrategy:
    def __init__(self, config: HMMPolicyConfig):
        self.cfg = config
        self.state = FeatureState(None, None, None, None)  # TODO M2: init deques
        self.metrics = type("M", (), {"count": lambda *a, **k: None})()
        self.portfolio = object()  # TODO M4: wire Nautilus portfolio
        self._last_action_ns = 0

    def on_order_book_delta(self, event):
        # TODO M4: fetch recent trades from cache
        feats = compute_features(None, event.book, [], self.state)
        # TODO M3: call /infer on ML service
        state, conf = 1, 0.7  # placeholder
        side, qty, limit_px = decide_action(state, conf, feats, self.cfg)
        block = check_gates(self, event.ts_ns, getattr(event.book, "spread_bp", 1.0), qty, self.portfolio, self.metrics)
        if block is not Block.OK or side == "HOLD":
            self.metrics.count("blocked", labels={"reason": block.value})
            return
        # TODO M4/M5: place order via Nautilus order API
