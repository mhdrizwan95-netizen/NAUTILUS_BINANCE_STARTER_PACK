#!/usr/bin/env python3
"""
ops/m19_scheduler.py — Autonomous Meta-Learning Scheduler

Reads live KPIs (Prometheus + logs), decides whether to trigger M15/M16/M17/M18
maintenance actions. Makes safe, cost-effective decisions with cooldowns and backoff.

Design Principles:
- Minimal intervention: Only act when needed, with lowest risk first
- Cooldown protection: Prevent action thrashing
- Rate limiting: Maximum actions per hour to avoid system overload
- Canaries preserved: All promotions still require validation
- State persistence: Remembers last actions for temporal awareness
- Configurable rules: Human-tunable thresholds without code changes
"""

import os
import json
import time
import math
import subprocess
import shlex
from datetime import datetime, timedelta
import yaml
from typing import Dict, List, Any, Optional, Tuple

CFG_PATH = os.path.join("ops", "m19_scheduler.yaml")
STATE_PATH = os.path.join("data", "processed", "m19", "scheduler_state.json")
OUT_DIR = os.path.join("data", "processed", "m19")
PROM_SNAPSHOT = os.path.join("data", "processed", "m19", "metrics_snapshot.json")

# Ensure output directory exists
os.makedirs(OUT_DIR, exist_ok=True)

def now() -> str:
    """Get current timestamp in ISO format."""
    return datetime.utcnow().isoformat()

def minutes_since(ts_iso: str) -> float:
    """Calculate minutes since the given ISO timestamp."""
    if not ts_iso:
        return float('inf')
    dt = datetime.fromisoformat(ts_iso)
    return (datetime.utcnow() - dt).total_seconds() / 60.0

def load_cfg() -> Dict[str, Any]:
    """Load scheduler configuration from YAML."""
    try:
        with open(CFG_PATH, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: Config file {CFG_PATH} not found, using defaults")
        return {
            "cooldowns": {"m15_minutes": 60, "m16_minutes": 120, "m17_minutes": 360, "m18_minutes": 90},
            "thresholds": {"drift_score_warn": 0.5, "drift_score_crit": 0.75,
                          "winrate_crit": 0.45, "macro_entropy_bits_warn": 0.9,
                          "cov_entropy_warn": 0.85, "feedback_stale_minutes": 30},
            "priorities": {"m16_on_winrate_crit": 100, "m17_on_macro_entropy": 90,
                          "noop_small_fluctuations": 0},
            "safeguards": {"canary_require_pass": True, "max_actions_per_hour": 2}
        }

def read_prom_snapshot() -> Dict[str, Any]:
    """
    Read current metrics snapshot.

    In production, this would read from your existing Prometheus/metrics exporter.
    For now, uses a JSON file that your dashboard/ML service can update.
    """
    try:
        if os.path.exists(PROM_SNAPSHOT):
            with open(PROM_SNAPSHOT, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not read metrics snapshot: {e}")

    # Safe defaults when no metrics available
    return {
        "drift_score": 0.0,
        "m16_avg_reward": 0.001,
        "m16_winrate": 0.52,
        "m16_entropy": 0.8,
        "macro_entropy_bits": 0.2,
        "cov_spectrum_entropy": 0.3,
        "guardrail_trigger_total_5m": 0,
        "feedback_fresh_minutes": 1,
        "rollups_age_minutes": 1,
        "corr_spike": 0.0,
        "timestamp": now()
    }

def load_state() -> Dict[str, Any]:
    """Load scheduler state including last run times and action counts."""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load state: {e}")

    # Initialize fresh state
    return {
        "last_run": {},
        "actions_in_last_hour": 0,
        "last_hour_epoch": int(time.time()) // 3600,
        "decision_log": [],
        "config_fingerprint": ""
    }

def save_state(state: Dict[str, Any]) -> None:
    """Save scheduler state to disk."""
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        print(f"Error saving state: {e}")

def cool_ok(state: Dict[str, Any], action_key: str, min_minutes: int) -> bool:
    """Check if enough time has passed since last run of this action."""
    last = state["last_run"].get(action_key, "")
    return minutes_since(last) >= min_minutes

def mark_run(state: Dict[str, Any], action_key: str) -> None:
    """Mark that an action was executed."""
    state["last_run"][action_key] = now()

def exec_shell(cmd: str) -> bool:
    """
    Execute a shell command safely.

    Returns True if command succeeded (exit code 0), False otherwise.
    """
    print(f"→ Executing: {cmd}")
    try:
        result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=3600)

        if result.returncode == 0:
            print("✅ Execution successful")
            return True
        else:
            print(f"❌ Execution failed (exit code {result.returncode})")
            if result.stderr:
                print(f"STDERR: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("⏰ Execution timed out")
        return False
    except Exception as e:
        print(f"⚠️  Execution error: {e}")
        return False

def assess_system_health(metrics: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess overall system health based on KPIs and determine if action is needed.

    Returns diagnostic information about system state.
    """
    th = cfg["thresholds"]
    health = {
        "overall_status": "healthy",
        "issues_found": [],
        "critical_count": 0,
        "warning_count": 0,
        "diagnostics": {}
    }

    # Drift score assessment
    drift = metrics.get("drift_score", 0.0)
    if drift >= th["drift_score_crit"]:
        health["issues_found"].append(f"drift_critical_{drift:.3f}")
        health["critical_count"] += 1
    elif drift >= th["drift_score_warn"]:
        health["issues_found"].append(f"drift_warning_{drift:.3f}")
        health["warning_count"] += 1

    # Win rate assessment
    winrate = metrics.get("m16_winrate", 0.5)
    if winrate <= th["winrate_crit"]:
        health["issues_found"].append(f"winrate_critical_{winrate:.3f}")
        health["critical_count"] += 1
    elif winrate <= th["winrate_warn"]:
        health["issues_found"].append(f"winrate_warning_{winrate:.3f}")
        health["warning_count"] += 1

    # Entropy assessments
    macro_entropy = metrics.get("macro_entropy_bits", 0.0)
    if macro_entropy >= th["macro_entropy_bits_warn"]:
        health["issues_found"].append(f"macro_entropy_high_{macro_entropy:.3f}")
        health["warning_count"] += 1

    cov_entropy = metrics.get("cov_spectrum_entropy", 0.0)
    if cov_entropy >= th["cov_entropy_warn"]:
        health["issues_found"].append(f"cov_entropy_high_{cov_entropy:.3f}")
        health["warning_count"] += 1

    # Data freshness
    feedback_age = metrics.get("feedback_fresh_minutes", 0)
    if feedback_age > th["feedback_stale_minutes"]:
        health["issues_found"].append(f"feedback_stale_{feedback_age:.0f}min")
        health["warning_count"] += 1

    rollups_age = metrics.get("rollups_age_minutes", 0)
    if rollups_age > th["rollups_stale_minutes"]:
        health["issues_found"].append(f"rollups_stale_{rollups_age:.0f}min")
        health["warning_count"] += 1

    # Correlation spikes
    corr_spike = metrics.get("corr_spike", 0.0)
    if corr_spike > 0.7:
        health["issues_found"].append(f"correlation_spike_{corr_spike:.3f}")
        health["warning_count"] += 1

    # Overall status
    if health["critical_count"] > 0:
        health["overall_status"] = "critical"
    elif health["warning_count"] > 0 or health["issues_found"]:
        health["overall_status"] = "needs_attention"

    health["diagnostics"] = {
        "drift_score": drift,
        "winrate": winrate,
        "macro_entropy": macro_entropy,
        "cov_entropy": cov_entropy,
        "feedback_age_min": feedback_age,
        "rollups_age_min": rollups_age,
        "correlation_spike": corr_spike
    }

    return health

def decide_and_act(cfg: Dict[str, Any], state: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Core decision logic: evaluate conditions and choose lowest-risk effective action.

    Returns detailed decision record for logging and analysis.
    """
    cd = cfg["cooldowns"]
    th = cfg["thresholds"]
    pri = cfg["priorities"]
    sg = cfg["safeguards"]

    decision = {
        "timestamp": now(),
        "decision": "noop",
        "reason": "no_triggers",
        "priority": pri["noop_small_fluctuations"],
        "action": None,
        "cause": None,
        "cooldown_ok": False,
        "metrics_sample": metrics
    }

    # Rate limiting check
    epoch_hr = int(time.time()) // 3600
    if epoch_hr != state["last_hour_epoch"]:
        state["actions_in_last_hour"] = 0
        state["last_hour_epoch"] = epoch_hr

    if state["actions_in_last_hour"] >= sg["max_actions_per_hour"]:
        decision.update({
            "decision": "rate_limited",
            "reason": f"max_actions_per_hour ({sg['max_actions_per_hour']}) exceeded"
        })
        return decision

    # Collect candidate actions with priorities
    candidates: List[Tuple[str, int, str]] = []

    # Critical conditions (highest priority)
    if metrics.get("m16_winrate", 0.5) <= th["winrate_crit"]:
        if cool_ok(state, "m16", cd["m16_minutes"]):
            candidates.append(("m16", pri["m16_on_winrate_crit"], "winrate_crit"))

    if metrics.get("drift_score", 0.0) >= th["drift_score_crit"]:
        if cool_ok(state, "m16", cd["m16_minutes"]):
            candidates.append(("m16", pri["m16_on_drift_crit"], "drift_crit"))

    # Warning conditions (medium priority)
    if metrics.get("macro_entropy_bits", 0.0) >= th["macro_entropy_bits_warn"]:
        if cool_ok(state, "m17", cd["m17_minutes"]):
            candidates.append(("m17", pri["m17_on_macro_entropy"], "macro_entropy"))

    if metrics.get("cov_spectrum_entropy", 0.0) >= th["cov_entropy_warn"]:
        if cool_ok(state, "m18", cd["m18_minutes"]):
            candidates.append(("m18", pri["m18_on_cov_entropy"], "cov_entropy"))

    if metrics.get("corr_spike", 0.0) > 0.7:
        if cool_ok(state, "m18", cd["m18_minutes"]):
            candidates.append(("m18", pri["m18_on_corr_spike"], "corr_spike"))

    if metrics.get("drift_score", 0.0) >= th["drift_score_warn"]:
        if cool_ok(state, "m15", cd["m15_minutes"]):
            candidates.append(("m15", pri["m15_on_drift_warn"], "drift_warn"))

    # Data freshness conditions (lower priority maintenance)
    if metrics.get("feedback_fresh_minutes", 0) > th["feedback_stale_minutes"]:
        if cool_ok(state, "m15", cd["m15_minutes"]):
            candidates.append(("paper_seed", pri["paper_seed_on_stale"], "feedback_stale"))

    if metrics.get("rollups_age_minutes", 0) > th["rollups_stale_minutes"]:
        if cool_ok(state, "m15", cd["m15_minutes"]):
            candidates.append(("paper_seed", pri["paper_seed_on_stale"], "rollups_stale"))

    # No action needed
    if not candidates:
        return decision

    # Choose highest priority action
    candidates.sort(key=lambda x: x[1], reverse=True)  # Sort by priority descending
    action, priority, cause = candidates[0]

    decision.update({
        "decision": "run",
        "action": action,
        "priority": priority,
        "cause": cause,
        "cooldown_ok": True
    })

    # Execute the chosen action
    success = False

    try:
        if action == "m16":
            # Full reinforcement with canary and promotion
            success = exec_shell("./ops/m16_reinforce.sh")

        elif action == "m15":
            # Fast calibration (cheap diagnostic)
            success = exec_shell("./ops/calibrate_fast.sh")

        elif action == "m17":
            # Macro/micro retraining
            success = (exec_shell("python ops/m17_train_macro.py") and
                      exec_shell("python ops/m17_train_micro.py"))

        elif action == "m18":
            # Covariance analysis/metrics refresh
            success = exec_shell("python ops/m18_cov_diag.py")

        elif action == "paper_seed":
            # Brief paper trading to refresh feedback data
            success = exec_shell("./ops/calibrate_paper.sh 300")  # 5 minutes

        if success:
            state["actions_in_last_hour"] += 1
            mark_run(state, action if action != "paper_seed" else "m15")
            decision.update({"ok": True, "executed_at": now()})
        else:
            decision.update({"ok": False, "error": "execution_failed"})

    except Exception as e:
        print(f"Error executing action {action}: {e}")
        decision.update({"ok": False, "error": str(e)})

    return decision

def main():
    """Main scheduler execution - evaluates system and decides on actions."""
    print("🧠 M19 Autonomous Meta-Learning Scheduler")
    print("=" * 50)

    try:
        # Load configuration and state
        cfg = load_cfg()
        state = load_state()

        print(f"Config loaded from {CFG_PATH}")
        print(f"State loaded from {STATE_PATH}")

        # Get current metrics
        metrics = read_prom_snapshot()
        print(f"Metrics snapshot: {len(metrics)} keys at {metrics.get('timestamp', 'unknown')}")

        # Assess system health
        health = assess_system_health(metrics, cfg)
        print(f"System health: {health['overall_status']} "
              f"({health['critical_count']} critical, {health['warning_count']} warnings)")

        if health['issues_found']:
            print(f"Issues found: {', '.join(health['issues_found'])}")

        # Make decision and act
        result = decide_and_act(cfg, state, metrics)

        # Update state with result
        state["decision_log"].append(result)
        # Keep only recent decisions (last 100)
        state["decision_log"] = state["decision_log"][-100:]

        # Save updated state
        save_state(state)

        # Print final result
        print(f"\n🎯 Decision: {result['decision']}")
        if result['decision'] == 'run':
            print(f"   Action: {result['action']}")
            print(f"   Cause: {result['cause']}")
            print(f"   Priority: {result['priority']}")
            print(f"   Success: {result.get('ok', 'unknown')}")

        # Return JSON for logging/cron monitoring
        print(f"\n{json.dumps(result, indent=2, default=str)}")
        return 0

    except Exception as e:
        print(f"❌ Scheduler error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
