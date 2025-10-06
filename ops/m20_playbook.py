#!/usr/bin/env python3
"""
ops/m20_playbook.py — M20 Response Playbooks

Pre-programmed recovery actions for different types of operational incidents.
Provides self-healing reflexes that automatically execute when anomalies are detected.

Playbook Categories:
- drawdown: Emergency risk reduction protocols
- guardrail_spike: Trading guardrail reset and restart procedures
- exchange_lag: API connectivity restoration and service restart
- entropy_spike: Uncertainty reduction measures

All playbooks are designed for safety, with graceful degradation and logging.
"""

import os
import subprocess
import shlex
import time
import logging
import asyncio
import aiohttp
from typing import List, Callable, Dict, Any
from datetime import datetime
from strategies.hmm_policy import telemetry

logger = logging.getLogger(__name__)

RECOVERY_LOG = os.path.join("data", "processed", "m20", "recovery_actions.jsonl")
os.makedirs(os.path.dirname(RECOVERY_LOG), exist_ok=True)

def run_command(cmd: str) -> bool:
    """
    Execute a shell command with proper error handling.

    Returns True on success (exit code 0) with logging.
    """
    print(f"🔄 Executing playbook action: {cmd}")
    try:
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=120  # 2-minute timeout for safety
        )

        if result.returncode == 0:
            print("✅ Action completed successfully")
            return True
        else:
            print(f"❌ Action failed (exit code {result.returncode})")
            if result.stderr and len(result.stderr.strip()) > 0:
                print(f"   Error output: {result.stderr.strip()}")
            return False

    except subprocess.TimeoutExpired:
        print("⏰ Action timed out")
        return False
    except Exception as e:
        print(f"⚠️  Action error: {e}")
        return False

def log_recovery_action(incident_types: List[str], action_name: str, success: bool) -> None:
    """Log recovery actions to persistent storage."""
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "incident_types": incident_types,
        "action": action_name,
        "success": success
    }

    try:
        with open(RECOVERY_LOG, "a") as f:
            import json
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"⚠️  Failed to log recovery action: {e}")

# =============================================================================
# PLAYBOOK ACTIONS
# =============================================================================

def reset_guardrails() -> bool:
    """
    Reset and restart trading guardrails.

    Actions:
    1. Archive current trading logs
    2. Stop current trading session(s)
    3. Restart with clean guardrail state
    """
    print("🏁 Playbook: Reset guardrails and restart trading")

    actions = [
        ("Archive logs", "python ops/rotate_logs.py 2>/dev/null || true"),
        ("Stop live trading", "pkill -TERM -f run_live.py || true"),
        ("Brief pause", "sleep 3"),
        ("Restart trading", "python ops/run_live.py --symbol BTCUSDT.BINANCE --dry-run true"),
    ]

    success = True
    for action_name, cmd in actions:
        if not run_command(cmd):
            print(f"   ⚠️  {action_name} failed, continuing...")
            success = False
            # Continue with other actions for partial recovery

    return success

def reconnect_exchange() -> bool:
    """
    Restore exchange API connectivity.

    Actions:
    1. Terminate unhealthy API connections
    2. Restart ML service (which handles exchange communication)
    3. Verify reconnection
    """
    print("🔌 Playbook: Reconnect exchange APIs")

    actions = [
        ("Terminate unhealthy connections", "pkill -TERM -f ml_service.app:app || true"),
        ("Brief pause for cleanup", "sleep 2"),
        ("Restart ML service", "uvicorn ml_service.app:app --host 0.0.0.0 --port 8010 &"),
        ("Pause for startup", "sleep 5"),
        ("Check ML service health", "curl -s http://127.0.0.1:8010/health >/dev/null"),
    ]

    success = True
    for action_name, cmd in actions:
        if not run_command(cmd):
            success = False
            # Continue attempting connection restoration

    return success

def reduce_risk() -> bool:
    """
    Temporarily reduce trading risk exposure.

    Actions:
    1. Set global risk reduction multiplier
    2. Restart trading with reduced position sizes
    3. Schedule automatic restoration (would be done via cron/daemon)
    """
    print("🛡️  Playbook: Reduce risk exposure (50% for 30 minutes)")

    risk_multiplier = 0.5
    duration_minutes = 30

    actions = [
        (f"Set risk multiplier to {risk_multiplier}",
         f"echo 'GLOBAL_RISK_MULTIPLIER={risk_multiplier}' >> .env"),
        ("Restart trading with reduced risk",
         "pkill -TERM -f run_live.py || true && sleep 2"),
        ("Launch reduced-risk trading",
         f"GLOBAL_RISK_MULTIPLIER={risk_multiplier} python ops/run_live.py --symbol BTCUSDT.BINANCE"),
    ]

    success = True
    for action_name, cmd in actions:
        if not run_command(cmd):
            success = False

    if success:
        print(f"   ⏱️  Risk reduction active for {duration_minutes} minutes")
        print("   (Automatic restoration requires additional cron job setup)"

    return success

def conservative_mode() -> bool:
    """
    Activate ultra-conservative trading mode.

    Actions:
    1. Switch to minimal position sizes
    2. Enable additional guardrails
    3. Reduce trading frequency
    """
    print("🐢 Playbook: Activate conservative trading mode")

    actions = [
        ("Enable conservative settings",
         "echo 'CONSERVATIVE_MODE=true' >> .env && echo 'MAX_POSITION_PCT=0.1' >> .env"),
        ("Restart with conservative params",
         "pkill -TERM -f run_live.py || true && sleep 2"),
        ("Launch conservative trading",
         "CONSERVATIVE_MODE=true MAX_POSITION_PCT=0.1 python ops/run_live.py --symbol BTCUSDT.BINANCE"),
    ]

    success = True
    for action_name, cmd in actions:
        if not run_command(cmd):
            success = False

    return success

def diagnostics_snapshot() -> bool:
    """
    Take comprehensive diagnostic snapshot.

    Actions:
    1. Run quick health checks
    2. Capture current state logs
    3. Generate diagnostic reports
    """
    print("🔬 Playbook: Capture diagnostics snapshot")

    actions = [
        ("Run quick system check", "./ops/quickcheck.sh"),
        ("Generate log summary", "python -c \"import sys; sys.path.insert(0, '.'); from ops.m20_detector import get_incident_summary; import json; print(json.dumps(get_incident_summary(24), indent=2))\" > data/processed/m20/diagnostics_snapshot.json"),
        ("M19 metrics snapshot", "python ops/m19_scheduler.py 2>/dev/null | grep -E '\"decision\"|\"incidents\"' | tail -3"),
    ]

    success = True
    for action_name, cmd in actions:
        if not run_command(cmd):
            success = False

    return success

# =============================================================================
# PLAYBOOK MAPPING
# =============================================================================

# Map incident types to appropriate response actions
PLAYBOOKS = {
    "drawdown": [
        reduce_risk,           # Immediate risk reduction
        conservative_mode,     # Switch to ultra-conservative mode
    ],

    "guardrail_spike": [
        reset_guardrails,      # Clear guardrail state and restart
        reduce_risk,          # Also reduce risk temporarily
        diagnostics_snapshot, # Capture what went wrong
    ],

    "exchange_lag": [
        reconnect_exchange,    # Restore API connectivity
        conservative_mode,     # Be more conservative while troubleshooting
    ],

    "entropy_spike": [
        reduce_risk,          # Uncertainty calls for caution
        diagnostics_snapshot, # Analyze what caused confusion
    ],

    "corr_spike": [
        diagnostics_snapshot, # Just understand the correlation event
        reduce_risk,          # Correlation spikes often precede volatility
    ]
}

def get_playbook_actions(incident_type: str) -> List[Callable[[], bool]]:
    """
    Get the appropriate playbook actions for an incident type.

    Args:
        incident_type: The detected incident type

    Returns:
        List of action functions in priority order
    """
    return PLAYBOOKS.get(incident_type, [diagnostics_snapshot])

# WS push identical to scheduler version
async def telemetry_ws_push(topic: str, payload: dict):
    DASH = os.environ.get("DASH_BASE", "http://127.0.0.1:8002")
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(f"{DASH}/ws/{topic}") as ws:
                await ws.send_json(payload)
    except Exception:
        pass

def execute(incidents: List[str]) -> Dict[str, Any]:
    """
    Execute appropriate playbooks for detected incidents.

    Args:
        incidents: List of incident types detected

    Returns:
        Summary of actions taken with success/failure status
    """
    print(f"🎭 Executing playbooks for incidents: {', '.join(incidents)}")

    executed_actions = []
    successful_actions = []
    failed_actions = []

    for incident_type in incidents:
        actions = get_playbook_actions(incident_type)

        for action_func in actions:
            action_name = action_func.__name__
            print(f"\n🎯 Executing {action_name} for {incident_type}")

            try:
                # Log the start of action
                log_recovery_action([incident_type], f"start_{action_name}", True)

                # Execute the action
                success = action_func()

                # --- new: record guardian incident for successful exec ---
                if success:
                    telemetry.inc_guardian_incident(incident_type)
                    payload = {
                        "ts": datetime.utcnow().isoformat(),
                        "incident": incident_type,
                        "action": action_name,
                    }
                    try:
                        import asyncio
                        asyncio.create_task(telemetry_ws_push("guardian", payload))
                    except Exception:
                        pass

                # Log the result
                log_recovery_action([incident_type], action_name, success)

                executed_actions.append(f"{incident_type}:{action_name}")

                if success:
                    successful_actions.append(f"{incident_type}:{action_name}")
                    print(f"✅ {action_name} completed successfully")
                else:
                    failed_actions.append(f"{incident_type}:{action_name}")
                    print(f"❌ {action_name} failed")

            except Exception as e:
                print(f"💥 Exception in {action_name}: {e}")
                failed_actions.append(f"{incident_type}:{action_name}")
                log_recovery_action([incident_type], action_name, False)

    return {
        "actions_attempted": executed_actions,
        "successful_actions": successful_actions,
        "failed_actions": failed_actions,
        "overall_success": len(failed_actions) == 0
    }

def get_recovery_history(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent recovery action history.

    Args:
        limit: Maximum number of actions to return

    Returns:
        List of recent recovery actions
    """
    if not os.path.exists(RECOVERY_LOG):
        return []

    actions = []
    try:
        with open(RECOVERY_LOG, "r") as f:
            for line in f:
                if line.strip():
                    actions.append(line.strip())

        # Return most recent actions first
        return actions[-limit:] if actions else []

    except Exception as e:
        print(f"Error reading recovery log: {e}")
        return []

if __name__ == "__main__":
    # Test playbooks with sample incidents
    print("Testing M20 playbooks with sample incidents...")

    test_incidents = ["drawdown", "guardrail_spike"]

    result = execute(test_incidents)
    print(f"\nTest Results:")
    print(f"  Actions attempted: {result['actions_attempted']}")
    print(f"  Successful: {result['successful_actions']}")
    print(f"  Failed: {result['failed_actions']}")
    print(f"  Overall success: {result['overall_success']}")

    # Show recent recovery history
    print(f"\nRecent recovery actions: {len(get_recovery_history(10))}")
