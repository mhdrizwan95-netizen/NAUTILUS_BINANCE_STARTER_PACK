#!/usr/bin/env python3
import json
import os
import random
from datetime import datetime

import httpx

HUB_URL = os.getenv("COLLECTIVE_HUB", "http://127.0.0.1:8090")
LOCAL_METRICS = "data/processed/m19/metrics_snapshot.json"
SYNC_LOG = "data/collective/sync_log.jsonl"
os.makedirs("data/collective", exist_ok=True)


def load_local_metrics():
    try:
        m = json.load(open(LOCAL_METRICS))
    except Exception:
        return {}
    # Minimal share
    keys = ["m16_avg_reward", "m16_winrate", "m16_entropy", "drift_score"]
    return {k: m.get(k, 0) for k in keys}


def jitter(x, scale=0.02):
    return x * (1 + random.uniform(-scale, scale))


def share_summary():
    summary = load_local_metrics()
    if not summary:
        return
    payload = {
        "node_id": os.getenv("NODE_ID", f"node-{random.randint(1000,9999)}"),
        "avg_reward": jitter(summary.get("m16_avg_reward", 0)),
        "winrate": jitter(summary.get("m16_winrate", 0)),
        "entropy": jitter(summary.get("m16_entropy", 0)),
        "drift_score": jitter(summary.get("drift_score", 0)),
    }
    try:
        r = httpx.post(f"{HUB_URL}/submit", json=payload, timeout=10)
        open(SYNC_LOG, "a").write(
            json.dumps(
                {
                    "time": datetime.utcnow().isoformat(),
                    "sent": payload,
                    "status": r.status_code,
                }
            )
            + "\n"
        )
    except Exception as e:
        open(SYNC_LOG, "a").write(
            json.dumps({"time": datetime.utcnow().isoformat(), "error": str(e)}) + "\n"
        )


def pull_consensus():
    try:
        r = httpx.get(f"{HUB_URL}/aggregate", timeout=10)
        if r.status_code == 200:
            data = r.json()
            path = "data/collective/consensus.json"
            json.dump(data, open(path, "w"), indent=2)
    except Exception as e:
        open(SYNC_LOG, "a").write(
            json.dumps({"time": datetime.utcnow().isoformat(), "pull_error": str(e)}) + "\n"
        )


if __name__ == "__main__":
    share_summary()
    pull_consensus()
