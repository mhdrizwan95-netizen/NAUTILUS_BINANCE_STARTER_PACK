"""
Real-Time Alerting & Anomaly Detection Daemon - M14 Monitoring & Awareness Layer.

The conciousness of your trading organism. Listens to event bus, evaluates conditions,
detects anomalies, and alerts stakeholders through multiple channels.

Design Philosophy:
- Event-driven reactive alerts (no polling)
- Configurable rules for maximum flexibility
- Multi-channel notifications (log, Telegram, webhooks, email)
- Statistical anomaly detection with rolling thresholds
- Throttling to prevent alert spam during extreme events
"""
import asyncio
import logging
import os
import re
import time
import statistics
from typing import Dict, List, Any, Optional, Callable
from collections import deque
from dataclasses import dataclass
import yaml

from .event_bus import BUS


@dataclass
class AlertRule:
    """Individual alert rule configuration."""
    topic: str
    condition: str
    message: str
    channels: List[str]
    priority: str = "medium"
    cooldown: int = 0  # Minimum seconds between alerts of same type

    def evaluate(self, data: Dict[str, Any]) -> bool:
        """Evaluate condition against event data."""
        try:
            # Safe evaluation with globals disabled
            result = eval(self.condition, {"__builtins__": {}}, {"data": data})
            return bool(result)
        except Exception as e:
            logging.warning(f"[ALERT] Rule evaluation error: {e}")
            return False

    def format_message(self, data: Dict[str, Any]) -> str:
        """Format alert message with event data."""
        try:
            # Add common data fields for formatting
            context = {
                **data,
                "timestamp": time.strftime("%H:%M:%S"),
                "priority": self.priority.upper()
            }
            return self.message.format(**context)
        except (KeyError, ValueError) as e:
            logging.warning(f"[ALERT] Message formatting error: {e}")
            return f"[ALERT] {self.topic}: {str(e)}"


@dataclass
class ThrottleConfig:
    """Alert throttling configuration."""
    enabled: bool = True
    window_seconds: int = 300
    max_alerts_per_window: int = 10


@dataclass
class AlertChannel:
    """Notification channel configuration."""
    enabled: bool = True
    token_env: Optional[str] = None
    chat_id_env: Optional[str] = None
    urls: Optional[List[str]] = None
    level: str = "WARNING"
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    sender_env: Optional[str] = None
    recipients: Optional[List[str]] = None


class AlertDaemon:
    """
    Core alerting engine that subscribes to event bus and triggers notifications.

    Features:
    - YAML rule configuration
    - Multiple notification channels
    - Throttling to prevent spam
    - Non-blocking async processing
    - Statistical anomaly detection
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.getenv("ALERT_CONFIG", "engine/config/alerts.yaml")
        self.rules: List[AlertRule] = []
        self.channels: Dict[str, AlertChannel] = {}
        self.throttling = ThrottleConfig()
        self._alert_history = deque(maxlen=1000)  # Recent alerts for throttling
        self._running = False

        self._load_config()
        self._setup_subscriptions()

    def _load_config(self) -> None:
        """Load alert rules and channel configuration."""
        if not os.path.exists(self.config_path):
            logging.warning(f"[ALERT] Config file not found: {self.config_path}")
            return

        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)

            # Load rules
            for rule_data in config.get("rules", []):
                rule = AlertRule(
                    topic=rule_data["topic"],
                    condition=rule_data["condition"],
                    message=rule_data["message"],
                    channels=rule_data.get("channels", ["log"]),
                    priority=rule_data.get("priority", "medium"),
                    cooldown=rule_data.get("cooldown", 0)
                )
                self.rules.append(rule)

            # Load throttling config
            throttle_cfg = config.get("throttling", {})
            self.throttling = ThrottleConfig(
                enabled=throttle_cfg.get("enabled", True),
                window_seconds=throttle_cfg.get("window_seconds", 300),
                max_alerts_per_window=throttle_cfg.get("max_alerts_per_window", 10)
            )

            # Load channels config
            for chan_name, chan_cfg in config.get("channels", {}).items():
                channel = AlertChannel(
                    enabled=chan_cfg.get("enabled", True),
                    token_env=chan_cfg.get("token_env"),
                    chat_id_env=chan_cfg.get("chat_id_env"),
                    urls=chan_cfg.get("urls"),
                    level=chan_cfg.get("level", "WARNING"),
                    smtp_server=chan_cfg.get("smtp_server"),
                    smtp_port=chan_cfg.get("smtp_port"),
                    sender_env=chan_cfg.get("sender_env"),
                    recipients=chan_cfg.get("recipients", [])
                )
                self.channels[chan_name] = channel

            logging.info(f"[ALERT] Loaded {len(self.rules)} rules for {len(self.channels)} channels")

        except Exception as e:
            logging.error(f"[ALERT] Failed to load config: {e}")

    def _setup_subscriptions(self) -> None:
        """Subscribe to event bus topics."""
        topic_handlers = {}  # topic -> handler function

        for rule in self.rules:
            if rule.topic not in topic_handlers:
                topic_handlers[rule.topic] = self._create_handler(rule.topic)
                BUS.subscribe(rule.topic, topic_handlers[rule.topic])

    def _create_handler(self, topic: str) -> Callable:
        """Create event handler for a specific topic."""

        async def handle_event(data: Dict[str, Any]) -> None:
            """Process events for this topic against all matching rules."""
            for rule in self.rules:
                if rule.topic != topic:
                    continue

                # Evaluate rule condition
                if not rule.evaluate(data):
                    continue

                # Check throttling
                if self._should_throttle():
                    logging.debug(f"[ALERT] Throttling alert: {rule.message}")
                    continue

                # Check rule cooldown
                if self._should_cooldown(rule):
                    continue

                # Format and send message
                message = rule.format_message(data)

                # Send via configured channels
                for channel_name in rule.channels:
                    if channel_name in self.channels and self.channels[channel_name].enabled:
                        await self._send_notification(channel_name, message, rule.priority)

                # Record alert
                self._record_alert(rule.topic, message)

        return handle_event

    async def _send_notification(self, channel_name: str, message: str, priority: str) -> None:
        """Send notification via specified channel."""
        channel = self.channels.get(channel_name)
        if not channel:
            return

        try:
            if channel_name == "log":
                level = getattr(logging, channel.level.upper(), logging.WARNING)
                logging.log(level, message)

            elif channel_name == "telegram":
                await self._send_telegram(channel, message)

            elif channel_name == "webhook":
                await self._send_webhook(channel, message, priority)

            elif channel_name == "email":
                await self._send_email(channel, message, priority)

        except Exception as e:
            logging.error(f"[ALERT] Failed to send {channel_name} notification: {e}")

    async def _send_telegram(self, channel: AlertChannel, message: str) -> None:
        """Send Telegram notification."""
        import aiohttp

        token = os.getenv(channel.token_env or "TELEGRAM_TOKEN")
        chat_id = os.getenv(channel.chat_id_env or "TELEGRAM_CHAT_ID")

        if not token or not chat_id:
            logging.warning("[ALERT] Telegram credentials not configured")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }) as response:
                if response.status != 200:
                    logging.error(f"[ALERT] Telegram send failed: {await response.text()}")

    async def _send_webhook(self, channel: AlertChannel, message: str, priority: str) -> None:
        """Send webhook notification."""
        import aiohttp

        if not channel.urls:
            return

        payload = {
            "timestamp": time.time(),
            "priority": priority,
            "message": message,
            "source": "trading-engine"
        }

        async with aiohttp.ClientSession() as session:
            for url in channel.urls:
                try:
                    async with session.post(url, json=payload, timeout=5) as response:
                        response.raise_for_status()
                except Exception as e:
                    logging.warning(f"[ALERT] Webhook failed for {url}: {e}")

    async def _send_email(self, channel: AlertChannel, message: str, priority: str) -> None:
        """Send email notification."""
        import smtplib
        from email.mime.text import MIMEText
        import ssl

        if not channel.smtp_server or not channel.recipients:
            return

        msg = MIMEText(message, "plain")
        msg["Subject"] = f"Trading Alert - {priority.upper()}"
        msg["From"] = os.getenv(channel.sender_env or "ALERT_SENDER_EMAIL", "alerts@trading-system")
        msg["To"] = ", ".join(channel.recipients)

        try:
            context = ssl.create_default_context()

            server = smtplib.SMTP(channel.smtp_server, channel.smtp_port or 587)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()

            # You'll want to configure proper authentication
            server.sendmail(msg["From"], channel.recipients, msg.as_string())
            server.quit()

        except Exception as e:
            logging.error(f"[ALERT] Email send failed: {e}")

    def _should_throttle(self) -> bool:
        """Check if alerts should be throttled."""
        if not self.throttling.enabled:
            return False

        now = time.time()
        window_start = now - self.throttling.window_seconds

        # Count recent alerts
        recent_count = sum(1 for alert in self._alert_history
                          if alert["timestamp"] > window_start)

        return recent_count >= self.throttling.max_alerts_per_window

    def _should_cooldown(self, rule: AlertRule) -> bool:
        """Check if rule is in cooldown period."""
        if rule.cooldown == 0:
            return False

        now = time.time()
        for alert in reversed(self._alert_history):
            if (alert["rule_topic"] == rule.topic and
                now - alert["timestamp"] < rule.cooldown):
                return True

        return False

    def _record_alert(self, topic: str, message: str) -> None:
        """Record alert for throttling and analytics."""
        self._alert_history.append({
            "timestamp": time.time(),
            "rule_topic": topic,
            "message": message
        })

    def get_stats(self) -> Dict[str, Any]:
        """Get alerting statistics."""
        return {
            "total_alerts": len(self._alert_history),
            "rules_loaded": len(self.rules),
            "channels_configured": len(self.channels),
            "throttling_enabled": self.throttling.enabled,
            "recent_alerts": list(self._alert_history)[-5:]  # Last 5
        }


class AnomalyWatcher:
    """
    Statistical anomaly detection for metrics and performance indicators.

    Monitors rolling statistics and flags deviations beyond sigma thresholds.
    """

    def __init__(self, window_size: int = 20, sigma_threshold: float = 3.0):
        self.window_size = window_size
        self.sigma_threshold = sigma_threshold
        self.metric_history: Dict[str, deque] = {}
        self.anomaly_alert = AlertDaemon()

        BUS.subscribe("metrics.update", lambda d: asyncio.create_task(self.on_metrics_update(d)))

    async def on_metrics_update(self, data: Dict[str, Any]) -> None:
        """Process metrics update and check for anomalies."""
        for metric_name in ["pnl_unrealized", "equity_usd", "exposure_usd"]:
            value = data.get(metric_name)
            if value is None or not isinstance(value, (int, float)):
                continue

            # Ensure metric history deque exists
            if metric_name not in self.metric_history:
                self.metric_history[metric_name] = deque(maxlen=self.window_size)

            self.metric_history[metric_name].append(value)

            # Check for anomalies if we have enough data
            history = self.metric_history[metric_name]
            if len(history) >= self.window_size:
                if self._detect_anomaly(history):
                    await self._alert_anomaly(metric_name, value, history)

    def _detect_anomaly(self, values: deque) -> bool:
        """Detect statistical anomalies using sigma deviation."""
        if len(values) < 2:
            return False

        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)  # Population standard deviation

        if stdev == 0:
            return False

        current = values[-1]  # Latest value
        z_score = abs(current - mean) / stdev

        return z_score > self.sigma_threshold

    async def _alert_anomaly(self, metric_name: str, value: float, history: deque) -> None:
        """Send anomaly alert."""
        mean = statistics.mean(history)
        stdev = statistics.pstdev(history)

        message = (f"📊 ANOMALY: {metric_name} = {value:.2f} deviates "
                  f"{self.sigma_threshold:.1f}σ from mean {mean:.2f} "
                  f"(stdev: {stdev:.2f})")

        await self.anomaly_alert._send_notification("log", message, "high")

        # Also notify via telegram if configured
        if "telegram" in self.anomaly_alert.channels and self.anomaly_alert.channels["telegram"].enabled:
            await self.anomaly_alert._send_notification("telegram", message, "high")

    def get_stats(self) -> Dict[str, Any]:
        """Get anomaly detection statistics."""
        return {
            "metrics_tracked": list(self.metric_history.keys()),
            "window_size": self.window_size,
            "sigma_threshold": self.sigma_threshold,
            "anomalies_detected": "tracked via alerts"
        }


# Global instances
_alert_daemon = None
_anomaly_watcher = None

async def initialize_alerting() -> None:
    """Initialize the alert system."""
    global _alert_daemon, _anomaly_watcher

    _alert_daemon = AlertDaemon()
    _anomaly_watcher = AnomalyWatcher()

    logging.info("[ALERT] Alert system initialized with real-time monitoring")

async def shutdown_alerting() -> None:
    """Shutdown the alert system."""
    global _alert_daemon, _anomaly_watcher

    _alert_daemon = None
    _anomaly_watcher = None

    logging.info("[ALERT] Alert system shutdown")
