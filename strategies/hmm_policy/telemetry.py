# strategies/hmm_policy/telemetry.py — M9 telemetry helpers (Prometheus-friendly)
from prometheus_client import CollectorRegistry, Counter, Gauge

_registry = CollectorRegistry()
guardrail_counter = Counter("guardrail_trigger_total", "Guardrail triggers", ["reason"], registry=_registry)
state_gauge      = Gauge("state_active", "Active HMM state", ["id"], registry=_registry)
pnl_realized     = Gauge("pnl_realized", "Realized PnL", registry=_registry)
pnl_unrealized   = Gauge("pnl_unrealized", "Unrealized PnL", registry=_registry)
drift_score      = Gauge("drift_score", "Feature drift (KLD)", registry=_registry)

# ✨ New metrics for Dashboard v2
policy_confidence  = Gauge("policy_confidence", "Latest policy decision confidence (0..1)", registry=_registry)
order_fill_ratio   = Gauge("order_fill_ratio", "Recent fills/orders ratio (0..1)", registry=_registry)
venue_latency_ms   = Gauge("venue_latency_ms", "Most recent venue latency (ms)", registry=_registry)
m19_actions_total  = Counter("m19_actions_total", "Total scheduler actions triggered", ["action"], registry=_registry)
m20_incidents_total= Counter("m20_incidents_total", "Total guardian incidents by type", ["type"], registry=_registry)

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

# --- New helpers ---
def set_policy_confidence(value: float):
    """Set the most recent model decision confidence (0..1)."""
    try: policy_confidence.set(max(0.0, min(1.0, float(value))))
    except Exception: pass

def set_order_fill_ratio(value: float):
    """Set recent fill ratio (fills / orders over short window)."""
    try: order_fill_ratio.set(max(0.0, min(1.0, float(value))))
    except Exception: pass

def observe_venue_latency_ms(value: float):
    """Record latest venue latency measurement (ms)."""
    try: venue_latency_ms.set(max(0.0, float(value)))
    except Exception: pass

def inc_scheduler_action(action: str):
    """Increment scheduler action counter for given action label."""
    try: m19_actions_total.labels(action=str(action)).inc()
    except Exception: pass

def inc_guardian_incident(incident_type: str):
    """Increment guardian incident counter."""
    try: m20_incidents_total.labels(type=str(incident_type)).inc()
    except Exception: pass
