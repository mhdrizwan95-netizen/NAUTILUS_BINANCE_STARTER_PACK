from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json, time, os

DATA_DIR = Path(os.getenv("OPS_DATA_DIR", "data"))
RUNTIME_DIR = DATA_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
SNAP_PATH = RUNTIME_DIR / "metrics_snapshot.json"

@dataclass
class Metrics:
    pnl_realized: float = 0.0
    pnl_unrealized: float = 0.0
    drift_score: float = 0.0
    policy_confidence: float = 0.0
    order_fill_ratio: float = 0.0
    venue_latency_ms: float = 0.0
    # NEW: account metrics
    account_equity_usd: float = 0.0
    cash_usd: float = 0.0
    gross_exposure_usd: float = 0.0

@dataclass
class Snapshot:
    metrics: Metrics
    ts: float

_STORE: Snapshot | None = None

def load() -> Snapshot:
    global _STORE
    if _STORE is not None:
        return _STORE
    if SNAP_PATH.exists():
        j = json.loads(SNAP_PATH.read_text())
        _STORE = Snapshot(metrics=Metrics(**j.get("metrics", {})), ts=j.get("ts", time.time()))
        return _STORE
    _STORE = Snapshot(metrics=Metrics(), ts=time.time())
    return _STORE

def save(s: Snapshot) -> None:
    global _STORE
    _STORE = s
    SNAP_PATH.write_text(json.dumps({"metrics": asdict(s.metrics), "ts": s.ts}, indent=2))
