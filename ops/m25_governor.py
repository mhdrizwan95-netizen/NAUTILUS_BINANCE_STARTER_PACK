#!/usr/bin/env python3
import os
import json
import yaml
from datetime import datetime

POLICY_PATH = "ops/m25_policy.yaml"
LOG_PATH = "data/processed/m25/compliance_log.jsonl"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def load_policy():
    return yaml.safe_load(open(POLICY_PATH))


def log_event(event):
    event["time"] = datetime.utcnow().isoformat()
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")


def check_risk_limits(r, policy):
    alerts = []
    lim = policy["risk_limits"]
    if r.get("daily_loss_usd", 0) < -lim["max_daily_loss_usd"]:
        alerts.append("DAILY_LOSS_LIMIT")
    if r.get("position_usd", 0) > lim["max_position_usd"]:
        alerts.append("POSITION_LIMIT")
    if r.get("leverage", 0) > lim["max_leverage"]:
        alerts.append("LEVERAGE_LIMIT")
    if r.get("open_trades", 0) > lim["max_open_trades"]:
        alerts.append("OPEN_TRADES_LIMIT")
    return alerts


def enforce(alerts):
    if not alerts:
        return
    # Simplest enforcement: halt trading
    print("[M25] Violations detected:", alerts)
    os.environ["TRADING_ENABLED"] = "false"
    log_event({"violations": alerts, "action": "TRADING_DISABLED"})


if __name__ == "__main__":
    policy = load_policy()
    # Example: gather runtime metrics from m19 snapshot
    snap_path = "data/processed/m19/metrics_snapshot.json"
    try:
        metrics = json.load(open(snap_path))
    except:
        metrics = {}
    alerts = check_risk_limits(metrics, policy)
    enforce(alerts)
