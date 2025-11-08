from __future__ import annotations

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from .events import publish
from .events import router as events_router
from .matcher import Matcher
from .store import SituationStore

APP = FastAPI(title="situations")
S = SituationStore()
M = Matcher(S)
APP.include_router(events_router)


@APP.on_event("startup")
async def boot():
    await S.load()


@APP.post("/control/priorities")
def priorities(body: dict):
    for u in body.get("updates", []):
        S.update_priority(u["name"], u["priority"])
    return {"ok": True}


@APP.post("/ingest/bar")
async def ingest_bar(body: dict):
    hits = M.evaluate(body["symbol"], body.get("features", {}), ts=body.get("ts"))
    for h in hits:
        _on_hit(h)
        await publish(h)
    return {"hits": len(hits)}


@APP.get("/health")
def health():
    return {"ok": True}


# --- Metrics ---------------------------------------------------------------

REG = CollectorRegistry()
HITS = Counter("situation_hits_total", "Total situation matches", ["name"], registry=REG)
EV_MEAN = Gauge("situation_ev_mean", "Online mean EV per situation (USD)", ["name"], registry=REG)
EV_CI_LOW = Gauge("situation_ev_ci_low", "95% CI low for EV", ["name"], registry=REG)
EV_CI_HIGH = Gauge("situation_ev_ci_high", "95% CI high for EV", ["name"], registry=REG)
NOVELTY_RATE = Gauge(
    "situation_novelty_rate",
    "Fraction of hits counted as novel",
    ["name"],
    registry=REG,
)
DECISIONS = Counter(
    "situation_decisions_total",
    "Bandit decisions by situation",
    ["name", "decision"],
    registry=REG,
)

_SYMBOL_SEEN: dict[str, set[str]] = {}
_NOVEL_COUNTS: dict[str, dict[str, float]] = {}  # name -> {"novel": x, "total": y}
_EV: dict[str, dict[str, float]] = {}  # name -> {n, mean, m2}


def _on_hit(hit: dict):
    name = hit.get("situation")
    sym = hit.get("symbol")
    if not name:
        return
    HITS.labels(name=name).inc()
    seen = _SYMBOL_SEEN.setdefault(name, set())
    counts = _NOVEL_COUNTS.setdefault(name, {"novel": 0.0, "total": 0.0})
    counts["total"] += 1.0
    if sym not in seen:
        seen.add(sym)
        counts["novel"] += 1.0
    rate = (counts["novel"] / counts["total"]) if counts["total"] > 0 else 0.0
    NOVELTY_RATE.labels(name=name).set(rate)


@APP.post("/feedback/outcome")
async def feedback(body: dict):
    # body: {event_id, situation?, pnl_usd, hold_sec, filled}
    name = body.get("situation") or (body.get("event_id", "::").split(":")[1])
    pnl = float(body.get("pnl_usd", 0.0))
    stats = _EV.setdefault(name, {"n": 0.0, "mean": 0.0, "m2": 0.0})
    # Welford online update
    stats["n"] += 1.0
    n = stats["n"]
    delta = pnl - stats["mean"]
    stats["mean"] += delta / n
    stats["m2"] += delta * (pnl - stats["mean"])
    mean = stats["mean"]
    var = (stats["m2"] / (n - 1.0)) if n > 1 else 0.0
    std = var**0.5
    se = (std / (n**0.5)) if n > 0 else 0.0
    ci_low = mean - 1.96 * se
    ci_high = mean + 1.96 * se
    EV_MEAN.labels(name=name).set(mean)
    EV_CI_LOW.labels(name=name).set(ci_low)
    EV_CI_HIGH.labels(name=name).set(ci_high)

    # Simple UCB priority update (optional): normalize UCB to [0,1]
    # UCB = mean + c * sqrt(ln N / n)
    c = 1.0
    total_n = sum(int(v.get("n", 0)) for v in _EV.values()) or 1
    ucb_scores = {}
    for nm, st in _EV.items():
        nn = max(st.get("n", 1.0), 1.0)
        ucb = st.get("mean", 0.0) + c * ((max(total_n, 1) ** 0.5) / (nn**0.5))
        ucb_scores[nm] = ucb
    # min-max scale
    mn = min(ucb_scores.values())
    mx = max(ucb_scores.values())
    span = (mx - mn) or 1.0
    for nm, sc in ucb_scores.items():
        prio = (sc - mn) / span
        S.update_priority(nm, prio)
        decision = "explore" if _EV[nm]["n"] < 10 else "exploit"
        DECISIONS.labels(name=nm, decision=decision).inc()
    return {"ok": True, "mean": mean, "ci": [ci_low, ci_high]}


@APP.get("/metrics")
def metrics():
    payload = generate_latest(REG)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
