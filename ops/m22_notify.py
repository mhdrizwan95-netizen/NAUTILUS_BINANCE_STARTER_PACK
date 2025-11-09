#!/usr/bin/env python3
"""
ops/m22_notify.py — Message Broadcasting Utility

Command-line utility for sending organism incidents and alerts to external platforms.
Provides a simple interface for broadcasting important events from the M20-M21 systems.

Supports Telegram, Discord, and Slack platforms through webhooks and API tokens.
Can be called from other scripts (like M20 guardian) to automatically report incidents.
"""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

import httpx

from ops.net import create_async_client, request_with_retry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK", "")
_JSON_ERRORS = (OSError, json.JSONDecodeError)
_SEND_ERRORS = (httpx.HTTPError, httpx.RequestError)

# Incident log paths
INCIDENT_LOG = os.path.join("data", "processed", "m20", "incident_log.jsonl")
RECOVERY_LOG = os.path.join("data", "processed", "m20", "recovery_actions.jsonl")


def read_last_incident() -> dict[str, Any] | None:
    """
    Read the most recent incident from the M20 incident log.

    Returns:
        Most recent incident record, or None if no incidents exist
    """
    if not os.path.exists(INCIDENT_LOG):
        logger.warning("No incident log found")
        return None

    try:
        with open(INCIDENT_LOG) as f:
            lines = f.readlines()
            if not lines:
                logger.info("No incidents in log")
                return None

            last_line = lines[-1].strip()
            if last_line:
                return json.loads(last_line)

    except _JSON_ERRORS:
        logger.exception("Error reading incident log")

    return None


def read_last_recovery() -> dict[str, Any] | None:
    """Read the most recent recovery action."""
    if not os.path.exists(RECOVERY_LOG):
        return None

    try:
        with open(RECOVERY_LOG) as f:
            lines = f.readlines()
            if not lines:
                return None

            last_line = lines[-1].strip()
            if last_line:
                return json.loads(last_line)

    except _JSON_ERRORS:
        logger.exception("Error reading recovery log")

    return None


def format_incident_message(incident: dict[str, Any]) -> str:
    """Format incident data into human-readable notification message."""
    timestamp = incident.get("timestamp", datetime.utcnow().isoformat())
    status = incident.get("status", "unknown").upper()
    incidents_list = incident.get("incidents", [])
    metrics = incident.get("metrics", {})

    message = "🚨 **Trading Organism Incident Detected**\n\n"
    message += f"**Status:** {status}\n"
    message += f"**Time:** {timestamp}\n\n"

    if incidents_list:
        message += "**Detected Issues:**\n"
        for issue in incidents_list:
            message += f"• {issue}\n"
        message += "\n"

    # Add key metrics
    relevant_metrics = {
        "PnL Drawdown": f"{metrics.get('pnl_drawdown_pct', 'N/A')}%",
        "Guardrail Rate": f"{metrics.get('guardrail_trigger_total_5m', 'N/A')} per 5min",
        "Exchange Latency": f"{metrics.get('exchange_latency_ms', 'N/A')}ms",
        "Macro Entropy": f"{metrics.get('macro_entropy_bits', 'N/A')}",
    }

    message += "**Key Metrics:**\n"
    for name, value in relevant_metrics.items():
        if value != "N/A":
            message += f"• {name}: {value}\n"

    return message


def format_recovery_message(recovery: dict[str, Any]) -> str:
    """Format recovery action data into notification message."""
    timestamp = recovery.get("timestamp", datetime.utcnow().isoformat())
    incidents = recovery.get("incident_types", [])
    action = recovery.get("action", "unknown")
    success = recovery.get("success", False)

    status_emoji = "✅" if success else "❌"
    message = f"{status_emoji} **Trading Organism Recovery Action**\n\n"
    message += f"**Action:** {action}\n"
    message += f"**Status:** {'SUCCESS' if success else 'FAILED'}\n"
    message += f"**Time:** {timestamp}\n"

    if incidents:
        message += f"**For Incidents:** {', '.join(incidents)}\n"

    return message


def format_custom_message(message: str, severity: str = "info", source: str = "system") -> str:
    """Format a custom message with standard header."""
    severity_emojis = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️", "success": "✅"}

    emoji = severity_emojis.get(severity.lower(), "💬")

    formatted = f"{emoji} **Trading Organism Notification**\n\n"
    formatted += f"**Source:** {source}\n"
    formatted += f"**Severity:** {severity.upper()}\n"
    formatted += f"**Message:** {message}\n"
    formatted += f"**Time:** {datetime.utcnow().isoformat()}"

    return formatted


async def send_to_platforms(message: str, platforms: list = None) -> dict[str, bool]:
    """
    Send message to configured platforms.

    Args:
        message: Message to send
        platforms: List of platforms ('telegram', 'discord', 'slack'). If None, uses all configured.

    Returns:
        Dictionary mapping platform to send success
    """
    if platforms is None:
        platforms = []
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            platforms.append("telegram")
        if DISCORD_WEBHOOK:
            platforms.append("discord")
        if SLACK_WEBHOOK:
            platforms.append("slack")

    if not platforms:
        logger.warning("No communication platforms configured")
        return {}

    results = {}

    async with create_async_client() as client:
        for platform in platforms:
            try:
                if platform == "telegram":
                    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
                        logger.warning("Telegram not properly configured")
                        results[platform] = False
                        continue

                    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                    payload = {
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": message,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    }

                    response = await request_with_retry(
                        client, "POST", url, json=payload, retries=2
                    )
                    response.raise_for_status()
                    results[platform] = True
                    logger.info("Message sent to Telegram")

                elif platform == "discord":
                    if not DISCORD_WEBHOOK:
                        logger.warning("Discord webhook not configured")
                        results[platform] = False
                        continue

                    payload = {"content": message}
                    response = await request_with_retry(
                        client, "POST", DISCORD_WEBHOOK, json=payload, retries=2
                    )
                    response.raise_for_status()
                    results[platform] = True
                    logger.info("Message sent to Discord")

                elif platform == "slack":
                    if not SLACK_WEBHOOK:
                        logger.warning("Slack webhook not configured")
                        results[platform] = False
                        continue

                    payload = {"text": message}
                    response = await request_with_retry(
                        client, "POST", SLACK_WEBHOOK, json=payload, retries=2
                    )
                    response.raise_for_status()
                    results[platform] = True
                    logger.info("Message sent to Slack")

                else:
                    logger.warning(f"Unknown platform: {platform}")
                    results[platform] = False

            except _SEND_ERRORS:
                logger.exception("Failed to send to %s", platform)
                results[platform] = False

    return results


async def main():
    """Main notification function."""
    parser = argparse.ArgumentParser(description="Trading Organism Notification Tool")
    parser.add_argument("--message", "-m", type=str, help="Custom message to send")
    parser.add_argument(
        "--severity",
        type=str,
        default="info",
        choices=["critical", "warning", "info", "success"],
        help="Message severity level",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="notification_tool",
        help="Message source identifier",
    )
    parser.add_argument(
        "--incident",
        action="store_true",
        help="Send notification about the most recent incident",
    )
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="Send notification about the most recent recovery action",
    )
    parser.add_argument(
        "--platforms",
        nargs="+",
        choices=["telegram", "discord", "slack"],
        help="Platforms to send to (defaults to all configured)",
    )

    args = parser.parse_args()

    message = None

    # Determine message content
    if args.incident:
        incident = read_last_incident()
        if incident:
            message = format_incident_message(incident)
            logger.info("Sending incident notification")
        else:
            logger.warning("No recent incident to report")
            return

    elif args.recovery:
        recovery = read_last_recovery()
        if recovery:
            message = format_recovery_message(recovery)
            logger.info("Sending recovery notification")
        else:
            logger.warning("No recent recovery action to report")
            return

    elif args.message:
        message = format_custom_message(args.message, args.severity, args.source)
        logger.info(f"Sending custom notification (severity: {args.severity})")

    else:
        logger.error("Must specify --message, --incident, or --recovery")
        parser.print_help()
        return

    if message:
        logger.debug(f"Sending message: {message[:100]}...")

        results = await send_to_platforms(message, args.platforms)

        # Report results
        successful = [p for p, s in results.items() if s]
        failed = [p for p, s in results.items() if not s]

        if successful:
            logger.info(f"Message sent successfully to: {', '.join(successful)}")
        if failed:
            logger.error(f"Failed to send to: {', '.join(failed)}")

        if not results:
            logger.warning("No platforms available for sending")


if __name__ == "__main__":
    asyncio.run(main())
