from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from json import JSONDecodeError
import json, time, os, tempfile

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
        raw = SNAP_PATH.read_text().strip()
        j = {}
        if raw:
            try:
                j = json.loads(raw)
            except JSONDecodeError:
                # Support concatenated/NDJSON style writes by taking the last valid line
                last = ""
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    last = line
                if last:
                    try:
                        j = json.loads(last)
                    except JSONDecodeError:
                        j = {}
        _STORE = Snapshot(metrics=Metrics(**j.get("metrics", {})), ts=j.get("ts", time.time()))
        return _STORE
    _STORE = Snapshot(metrics=Metrics(), ts=time.time())
    return _STORE


def save(s: Snapshot) -> None:
    global _STORE
    _STORE = s
    payload = json.dumps({"metrics": asdict(s.metrics), "ts": s.ts}, indent=2)
    tmp_dir = SNAP_PATH.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=tmp_dir, delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, SNAP_PATH)
