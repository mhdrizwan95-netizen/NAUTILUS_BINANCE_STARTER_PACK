#!/usr/bin/env python3
"""
ops/m20_detector.py — M20 Incident Detection

Monitors system metrics for operational anomalies and classifies incident types.
Part of the autonomous resilience system that enables self-healing reflexes.

Detection Capabilities:
- Equity drawdowns requiring risk reduction
- Guardrail trigger spikes indicating execution issues
- Exchange connectivity problems (latency spikes)
- Model confusion spikes (regime entropy changes)

Incident Types:
- drawdown: Excessive portfolio loss
- guardrail_spike: Trading guardrails triggering too frequently
- exchange_lag: API communication latency above threshold
- entropy_spike: Sudden increases in model uncertainty/confusion
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

INCIDENT_LOG = os.path.join("data", "processed", "m20", "incident_log.jsonl")
os.makedirs(os.path.dirname(INCIDENT_LOG), exist_ok=True)

# Configurable thresholds - could be moved to YAML config in production
THRESHOLDS = {
    "pnl_drawdown_pct": 5.0,      # % equity drop from peak
    "guardrail_rate": 20,         # guardrails per 5 minute window
    "exchange_latency_ms": 800,   # mean API latency threshold
    "entropy_spike": 0.3,         # sudden macro entropy increase
    "corr_spike": 0.7,            # correlation coefficient spike
}

# Track previous values for detecting spikes/changes
_previous_values = {
    "macro_entropy_bits": 0.0,
    "correlation_spike": 0.0,
}

def update_previous_values(metrics: Dict[str, Any]) -> None:
    """Update cached previous values for trend detection."""
    global _previous_values

    if "macro_entropy_bits" in metrics:
        _previous_values["macro_entropy_bits"] = metrics["macro_entropy_bits"]

    if "correlation_spike" in metrics:
        _previous_values["correlation_spike"] = metrics["correlation_spike"]

def assess_system_health(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Comprehensive system health assessment.

    Returns detailed health status with all checks and their results.
    """
    health = {
        "overall_status": "healthy",
        "checks_performed": [],
        "warnings": [],
        "critical_issues": []
    }

    # 1. P&L Drawdown Check
    drawdown_pct = metrics.get("pnl_drawdown_pct", 0.0)
    drawdown_status = "ok"
    if drawdown_pct > THRESHOLDS["pnl_drawdown_pct"]:
        drawdown_status = "critical" if drawdown_pct > 15.0 else "warning"
        health["critical_issues" if drawdown_status == "critical" else "warnings"].append("pnl_drawdown_pct")

    health["checks_performed"].append({
        "check": "pnl_drawdown",
        "status": drawdown_status,
        "value": drawdown_pct,
        "threshold": THRESHOLDS["pnl_drawdown_pct"],
        "units": "percent"
    })

    # 2. Guardrail Trigger Rate Check
    guardrail_rate = metrics.get("guardrail_trigger_total_5m", 0)
    guardrail_status = "ok"
    if guardrail_rate > THRESHOLDS["guardrail_rate"]:
        guardrail_status = "critical"
        health["critical_issues"].append("guardrail_trigger_total_5m")

    health["checks_performed"].append({
        "check": "guardrail_rate",
        "status": guardrail_status,
        "value": guardrail_rate,
        "threshold": THRESHOLDS["guardrail_rate"],
        "units": "triggers_per_5min"
    })

    # 3. Exchange Latency Check
    latency_ms = metrics.get("exchange_latency_ms", 0.0)
    latency_status = "ok"
    if latency_ms > THRESHOLDS["exchange_latency_ms"]:
        latency_status = "critical" if latency_ms > 2000.0 else "warning"
        health["critical_issues" if latency_status == "critical" else "warnings"].append("exchange_latency_ms")

    health["checks_performed"].append({
        "check": "exchange_latency",
        "status": latency_status,
        "value": latency_ms,
        "threshold": THRESHOLDS["exchange_latency_ms"],
        "units": "milliseconds"
    })

    # 4. Macro Entropy Spike Check
    entropy_current = metrics.get("macro_entropy_bits", 0.0)
    entropy_prev = _previous_values.get("macro_entropy_bits", entropy_current)
    entropy_change = entropy_current - entropy_prev

    entropy_status = "ok"
    if abs(entropy_change) > THRESHOLDS["entropy_spike"]:
        entropy_status = "warning" if abs(entropy_change) > THRESHOLDS["entropy_spike"] * 2 else "ok_warn"
        if abs(entropy_change) > THRESHOLDS["entropy_spike"] * 3:  # Very large spike
            entropy_status = "critical"
            health[("critical_issues" if entropy_status == "critical" else "warnings")].append("macro_entropy_bits")

    health["checks_performed"].append({
        "check": "entropy_spike",
        "status": entropy_status,
        "value": entropy_change,
        "threshold": THRESHOLDS["entropy_spike"],
        "units": "bits_change",
        "metadata": {"current": entropy_current, "previous": entropy_prev}
    })

    # 5. Correlation Spike Check
    corr_spike = metrics.get("corr_spike", 0.0)
    corr_status = "ok"
    if corr_spike > THRESHOLDS["corr_spike"]:
        corr_status = "critical"
        health["critical_issues"].append("corr_spike")

    health["checks_performed"].append({
        "check": "correlation_spike",
        "status": corr_status,
        "value": corr_spike,
        "threshold": THRESHOLDS["corr_spike"],
        "units": "coefficient"
    })

    # Determine overall health
    if health["critical_issues"]:
        health["overall_status"] = "critical"
    elif health["warnings"] or any(c["status"] in ["warning", "ok_warn"] for c in health["checks_performed"]):
        health["overall_status"] = "needs_attention"

    return health

def detect(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Primary incident detection function.

    Analyzes metrics against thresholds and returns incident classification.
    Logs incidents to persistent storage when detected.

    Returns incident report dict.
    """
    print("🔍 M20 Incident Detection: Checking system health...")

    # Assess comprehensive health
    health = assess_system_health(metrics)

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "status": health["overall_status"],
        "incidents": health["critical_issues"] + health["warnings"],
        "diagnostics": health
    }

    # If healthy or minor warnings, return clean status
    if result["status"] == "healthy":
        print("✅ System healthy - no incidents detected")
        update_previous_values(metrics)
        return result

    # Classify and log incident
    print(f"🚨 Health status: {result['status']}")
    if result["incidents"]:
        print(f"   Detected incidents: {', '.join(result['incidents'])}")

    # Create detailed incident record
    incident_record = {
        "timestamp": result["timestamp"],
        "status": result["status"],
        "incidents": result["incidents"],
        "metrics_sample": metrics,
        "health_assessment": health,
        "thresholds_used": THRESHOLDS,
        "previous_values": _previous_values.copy()
    }

    # Log incident to persistent storage
    try:
        with open(INCIDENT_LOG, "a") as f:
            f.write(json.dumps(incident_record, default=str) + "\n")
        print(f"📝 Incident logged to {INCIDENT_LOG}")
    except Exception as e:
        print(f"⚠️  Failed to log incident: {e}")

    # Update cached values for next comparison
    update_previous_values(metrics)

    return result

def get_recent_incidents(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Retrieve recent incident history.

    Args:
        limit: Maximum number of incidents to return

    Returns:
        List of recent incidents (most recent first)
    """
    incidents = []

    if not os.path.exists(INCIDENT_LOG):
        return incidents

    try:
        with open(INCIDENT_LOG, "r") as f:
            for line in f:
                if line.strip():
                    incidents.append(json.loads(line.strip()))

        # Return most recent incidents first
        return sorted(incidents, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]

    except Exception as e:
        print(f"Error reading incident log: {e}")
        return []

def get_incident_summary(hours: int = 24) -> Dict[str, Any]:
    """
    Generate summary statistics for recent incidents.

    Args:
        hours: Time window for summary in hours

    Returns:
        Summary statistics for incident analysis
    """
    cutoff_time = datetime.utcnow().timestamp() - (hours * 3600)
    incidents = get_recent_incidents(100)  # Get last 100 incidents

    # Filter to time window
    recent = [inc for inc in incidents
             if datetime.fromisoformat(inc["timestamp"]).timestamp() > cutoff_time]

    summary = {
        "time_window_hours": hours,
        "total_incidents": len(recent),
        "incidents_by_type": {},
        "incidents_by_status": {},
        "most_recent": recent[0] if recent else None
    }

    # Categorize incidents
    for incident in recent:
        status = incident.get("status", "unknown")
        summary["incidents_by_status"][status] = summary["incidents_by_status"].get(status, 0) + 1

        for incident_type in incident.get("incidents", []):
            summary["incidents_by_type"][incident_type] = summary["incidents_by_type"].get(incident_type, 0) + 1

    return summary

if __name__ == "__main__":
    # Test with sample metrics when run directly
    test_metrics = {
        "pnl_drawdown_pct": 2.5,  # Below threshold
        "guardrail_trigger_total_5m": 25,  # Above threshold
        "exchange_latency_ms": 1200,  # Above threshold
        "macro_entropy_bits": 0.8,  # For comparison
        "corr_spike": 0.3
    }

    print("Testing M20 detector with sample metrics...")
    result = detect(test_metrics)

    print(f"\nResult: {json.dumps(result, indent=2)}")

    # Test incident history
    summary = get_incident_summary(1)  # Last hour
    print(f"\nIncident summary: {json.dumps(summary, indent=2)}")
