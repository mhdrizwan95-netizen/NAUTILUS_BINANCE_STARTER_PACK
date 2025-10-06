
# strategies/hmm_policy/telemetry.py — M9 telemetry helpers (Prometheus-friendly)
from prometheus_client import CollectorRegistry, Counter, Gauge

_registry = CollectorRegistry()
guardrail_counter = Counter("guardrail_trigger_total", "Guardrail triggers", ["reason"], registry=_registry)
state_gauge = Gauge("state_active", "Active HMM state", ["id"], registry=_registry)
pnl_realized = Gauge("pnl_realized", "Realized PnL", registry=_registry)
pnl_unrealized = Gauge("pnl_unrealized", "Unrealized PnL", registry=_registry)
drift_score = Gauge("drift_score", "Feature drift (KLD)", registry=_registry)

def emit_guardrail(reason: str):
    guardrail_counter.labels(reason=reason).inc()

def set_state(state_id: int):
    # zeroing others requires external control; here we only mark the current
    state_gauge.labels(id=str(state_id)).set(1)

def set_pnl(realized: float | None = None, unrealized: float | None = None):
    if realized is not None: pnl_realized.set(realized)
    if unrealized is not None: pnl_unrealized.set(unrealized)

def set_drift(value: float):
    drift_score.set(value)

def registry():
    return _registry
