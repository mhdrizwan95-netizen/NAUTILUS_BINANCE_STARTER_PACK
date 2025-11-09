#!/usr/bin/env python3
"""
ops/m22_comms_service.py — M22 Communication Gateway

FastAPI microservice providing REST API access to organism state and decision-making,
enabling external systems and human operators to communicate with the trading organism.

Exposes structured status information from M19 scheduler, M20 guardian, and evolutionary memory,
while enabling bidirectional communication through alert posting for notifications via Telegram/Discord.

Communication capabilities enabled:
- Live status introspection (/status, /decisions, /incidents)
- Real-time alert broadcasting (/alert)
- Health monitoring (/health)
- Multi-platform notifications (Telegram, Discord, future: Slack, Teams)
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Trading Organism Communication Gateway",
    description="M22 Communication layer for the autonomous trading organism",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware for web dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration from environment
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK", "")
_JSON_ERRORS = (OSError, json.JSONDecodeError)
_HTTP_ERRORS = (httpx.HTTPError, httpx.RequestError)

# System data paths (compatible with M19-M21)
M19_STATE_FILE = os.path.join("data", "processed", "m19", "scheduler_state.json")
M19_METRICS_FILE = os.path.join("data", "processed", "m19", "metrics_snapshot.json")
M20_INCIDENT_LOG = os.path.join("data", "processed", "m20", "incident_log.jsonl")
M20_RECOVERY_LOG = os.path.join("data", "processed", "m20", "recovery_actions.jsonl")
M21_LINEAGE_INDEX = os.path.join("data", "memory_vault", "lineage_index.json")


def safe_json_load(filepath: str, default: Any = None) -> Any:
    """
    Safely load JSON file with error handling.

    Args:
        filepath: Path to the JSON file
        default: Default value to return if file doesn't exist or is invalid

    Returns:
        Parsed JSON data or default value
    """
    default = default or {}
    try:
        if os.path.exists(filepath):
            with open(filepath) as f:
                return json.load(f)
    except _JSON_ERRORS as exc:
        logger.warning("Failed to load %s: %s", filepath, exc)
    return default


def read_recent_incidents(limit: int = 10) -> list[dict[str, Any]]:
    """
    Read recent incident records from M20 incident log.

    Args:
        limit: Maximum number of recent incidents to return

    Returns:
        List of recent incident records
    """
    incidents = []
    if not os.path.exists(M20_INCIDENT_LOG):
        return incidents

    try:
        with open(M20_INCIDENT_LOG) as f:
            for line in f:
                if line.strip():
                    try:
                        incident = json.loads(line.strip())
                        incidents.append(incident)
                    except json.JSONDecodeError as exc:
                        logger.warning("Invalid incident JSON: %s", exc)

        incidents.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except _JSON_ERRORS:
        logger.exception("Error reading incident log")
        return []
    else:
        return incidents[:limit]


def read_recovery_actions(limit: int = 10) -> list[dict[str, Any]]:
    """Read recent recovery action records."""
    actions = []
    if not os.path.exists(M20_RECOVERY_LOG):
        return actions

    try:
        with open(M20_RECOVERY_LOG) as f:
            lines = f.readlines()[-limit:]

        for line in lines:
            if line.strip():
                try:
                    action = json.loads(line.strip())
                    actions.append(action)
                except json.JSONDecodeError as exc:
                    logger.warning("Invalid recovery action JSON: %s", exc)
    except _JSON_ERRORS:
        logger.exception("Error reading recovery action log")
        return []
    else:
        return actions


def get_evolutionary_summary() -> dict[str, Any]:
    """Get summary of organism evolutionary state from M21 lineage."""
    lineage = safe_json_load(M21_LINEAGE_INDEX, {"models": []})

    if not lineage["models"]:
        return {"status": "no_evolution_history", "total_generations": 0}

    # Get latest generation stats
    latest = lineage["models"][-1] if lineage["models"] else {}

    return {
        "total_generations": len(lineage["models"]),
        "latest_generation": latest.get("tag", "unknown"),
        "latest_timestamp": latest.get("archived_at", "unknown"),
        "performance_snapshot": latest.get("performance_snapshot", {}),
        "current_generation_type": latest.get("generation_type", "unknown"),
    }


def get_system_health() -> dict[str, Any]:
    """Aggregate health status from all system components."""
    # Load latest metrics and state
    state = safe_json_load(M19_STATE_FILE, {})

    # Recent incidents indicate system stress
    recent_incidents = read_recent_incidents(5)
    recent_incident_count = len(
        [inc for inc in recent_incidents if inc.get("status") == "critical"]
    )

    # Recent recovery actions show responsiveness
    recent_recoveries = read_recovery_actions(5)
    recent_success_recoveries = len([rec for rec in recent_recoveries if rec.get("success", False)])

    # Determine overall health
    health_status = "healthy"

    # Check for critical conditions
    if recent_incident_count > 0:
        health_status = "warning"
    if recent_incident_count >= 3:  # Multiple recent critical incidents
        health_status = "critical"

    # Check if scheduler is running (has recent decisions)
    last_decision_time = state.get("last_run", {}).get("decision_time")
    if last_decision_time:
        hours_since_decision = (
            datetime.utcnow() - datetime.fromisoformat(last_decision_time)
        ).total_seconds() / 3600
        if hours_since_decision > 2:  # No decisions in 2+ hours
            health_status = "warning"
        if hours_since_decision > 6:  # No decisions in 6+ hours
            health_status = "critical"

    return {
        "overall_status": health_status,
        "scheduler_active": bool(last_decision_time),
        "recent_critical_incidents": recent_incident_count,
        "recent_successful_recoveries": recent_success_recoveries,
        "last_scheduler_activity": last_decision_time,
    }


async def send_telegram_message(message: str) -> bool:
    """Send message to Telegram chat if configured."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured, skipping message")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }

            response = await client.post(url, json=payload)
            response.raise_for_status()

            logger.info("Message sent to Telegram chat %s", TELEGRAM_CHAT_ID)
            return True

    except _HTTP_ERRORS:
        logger.exception("Failed to send Telegram message")
        return False


async def send_discord_message(message: str) -> bool:
    """Send message to Discord webhook if configured."""
    if not DISCORD_WEBHOOK:
        logger.info("Discord webhook not configured, skipping message")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"content": message}
            response = await client.post(DISCORD_WEBHOOK, json=payload)
            response.raise_for_status()

            logger.info("Message sent to Discord webhook")
            return True

    except _HTTP_ERRORS:
        logger.exception("Failed to send Discord message")
        return False


async def send_slack_message(message: str) -> bool:
    """Send message to Slack webhook if configured."""
    if not SLACK_WEBHOOK:
        logger.info("Slack webhook not configured, skipping message")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"text": message}
            response = await client.post(SLACK_WEBHOOK, json=payload)
            response.raise_for_status()

            logger.info("Message sent to Slack webhook")
            return True

    except _HTTP_ERRORS:
        logger.exception("Failed to send Slack message")
        return False


async def broadcast_alert(message: str, platforms: list[str] = None) -> dict[str, bool]:
    """
    Broadcast alert message to configured platforms.

    Args:
        message: Alert message to send
        platforms: List of platforms to send to, defaults to all configured

    Returns:
        Dictionary of platform send results
    """
    if platforms is None:
        platforms = []

        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            platforms.append("telegram")

        if DISCORD_WEBHOOK:
            platforms.append("discord")

        if SLACK_WEBHOOK:
            platforms.append("slack")

    results = {}

    for platform in platforms:
        if platform.lower() == "telegram":
            results["telegram"] = await send_telegram_message(message)
        elif platform.lower() == "discord":
            results["discord"] = await send_discord_message(message)
        elif platform.lower() == "slack":
            results["slack"] = await send_slack_message(message)
        else:
            logger.warning(f"Unknown platform: {platform}")
            results[platform] = False

    return results


# ============================================================================
# API ENDPOINTS
# ============================================================================


@app.get("/")
def root():
    """Root endpoint with basic organism info."""
    return JSONResponse(
        {
            "service": "Trading Organism Communication Gateway",
            "version": "M22",
            "documentation": "/docs",
            "status": "/status",
            "health": "/health",
        }
    )


@app.get("/status")
def get_status():
    """
    Get comprehensive organism status from all cognitive layers.

    Returns aggregated status from M19 scheduler, M20 guardian, and M21 memory systems.
    """
    # Load current system state
    scheduler_state = safe_json_load(M19_STATE_FILE, {})
    current_metrics = safe_json_load(M19_METRICS_FILE, {})

    # Get health assessment
    health = get_system_health()

    # Get evolutionary context
    evolution = get_evolutionary_summary()

    # Recent incidents and recoveries
    incidents = read_recent_incidents(5)
    recoveries = read_recovery_actions(5)

    status = {
        "timestamp": datetime.utcnow().isoformat(),
        "organismic_id": "HMM-Trading-Organism-M15-M22",
        "cognitive_layers": [
            "M15-Calibration",
            "M16-Reinforcement",
            "M17-Hierarchical",
            "M18-Covariance",
            "M19-Meta-Intelligence",
            "M20-Resilience",
            "M21-Memory",
            "M22-Communication",
        ],
        "health": health,
        "current_state": scheduler_state.get("last_result", {}),
        "live_metrics": current_metrics,
        "evolution": evolution,
        "recent_incidents": incidents,
        "recent_recoveries": recoveries,
    }

    return JSONResponse(status)


@app.get("/decisions")
def get_decisions():
    """
    Get recent scheduler decisions from M19 meta-intelligence.

    Shows the organism's recent strategic thinking and actions.
    """
    state = safe_json_load(M19_STATE_FILE, {})

    decisions = {
        "last_decision": state.get("last_result", {}),
        "decision_history": state.get("decision_log", []),
        "scheduler_health": state.get("health", "unknown"),
        "cooldowns": state.get("last_run", {}),
    }

    return JSONResponse(decisions)


@app.get("/incidents")
def get_incidents(limit: int = 10):
    """
    Get incident history from M20 guardian system.

    Shows the organism's recent stress events and recovery attempts.
    """
    incidents = read_recent_incidents(limit)

    return JSONResponse(
        {
            "incidents": incidents,
            "total_available": len(read_recent_incidents(1000)),  # Approximate total
            "shown_limit": limit,
        }
    )


@app.get("/evolution")
def get_evolution():
    """Get evolutionary lineage information from M21 memory system."""
    evolution = get_evolutionary_summary()

    # Expand with lineage details
    lineage = safe_json_load(M21_LINEAGE_INDEX, {"models": []})
    evolution["lineage"] = lineage

    return JSONResponse(evolution)


@app.post("/alert")
async def post_alert(alert_payload: dict[str, Any], background_tasks: BackgroundTasks):
    """
    Send alert message via configured communication platforms.

    Endpoint accepts alert data and broadcasts to Telegram/Discord/Slack
    based on environment configuration.
    """
    message = alert_payload.get("message", "")
    severity = alert_payload.get("severity", "info")
    source = alert_payload.get("source", "unknown")
    details = alert_payload.get("details", {})

    if not message:
        raise HTTPException(status_code=400, detail="Alert message required")

    # Format message for chat platforms
    formatted_message = "🚨 **Trading Organism Alert**\n\n"
    formatted_message += f"**Source:** {source}\n"
    formatted_message += f"**Severity:** {severity.upper()}\n"
    formatted_message += f"**Message:** {message}\n"

    if details:
        formatted_message += "\n**Details:**\n"
        for key, value in details.items():
            formatted_message += f"• {key}: {value}\n"

    formatted_message += f"\n🕒 {datetime.utcnow().isoformat()}"

    # Broadcast in background to avoid blocking
    background_tasks.add_task(broadcast_alert, formatted_message)

    return JSONResponse(
        {
            "status": "alert_queued",
            "message": message,
            "severity": severity,
            "platforms_configured": [
                p
                for p in ["telegram", "discord", "slack"]
                if (p == "telegram" and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
                or (p == "discord" and DISCORD_WEBHOOK)
                or (p == "slack" and SLACK_WEBHOOK)
            ],
        }
    )


@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    health = get_system_health()

    # Return appropriate HTTP status based on health
    status_code = 200
    if health["overall_status"] == "warning":
        status_code = 200  # Still healthy, but warn
    elif health["overall_status"] == "critical":
        status_code = 503  # Service unavailable

    return JSONResponse(
        status_code=status_code,
        content={
            "service": "Trading Organism Comms Gateway",
            "status": health["overall_status"],
            "timestamp": datetime.utcnow().isoformat(),
            "version": "M22",
        },
    )


@app.get("/metrics")
def prometheus_metrics():
    """Provide metrics in Prometheus format for monitoring."""
    health = get_system_health()
    evolution = get_evolutionary_summary()

    # Create Prometheus-format metrics
    status_map = {"healthy": 0, "warning": 1, "critical": 2}
    status_value = status_map.get(health["overall_status"], -1)

    metrics = f"""# Trading Organism M15-M22 Metrics
# HELP organism_health_status Current health status (0=healthy, 1=warning, 2=critical)
# TYPE organism_health_status gauge
organism_health_status{{service="comms_gateway"}} {status_value}

# HELP organism_total_generations Total evolutionary generations
# TYPE organism_total_generations gauge
organism_total_generations {evolution.get("total_generations", 0)}

# HELP organism_recent_critical_incidents Critical incidents in recent history
# TYPE organism_recent_critical_incidents gauge
organism_recent_critical_incidents {health.get("recent_critical_incidents", 0)}

# HELP organism_recent_recoveries Successful recovery actions
# TYPE organism_recent_recoveries gauge
organism_recent_recoveries {health.get("recent_successful_recoveries", 0)}
"""

    return PlainTextResponse(metrics, media_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    # Run with uvicorn for testing
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
