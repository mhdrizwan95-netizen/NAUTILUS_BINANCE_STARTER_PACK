"""Unified notification service for trade events.

Supports both Slack and Telegram notifications for:
- Trade executions (fills)
- Strategy signals
- Risk alerts
- Daily summaries
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from loguru import logger


@dataclass
class NotificationConfig:
    """Configuration for notification channels."""
    
    # Telegram
    telegram_enabled: bool = field(
        default_factory=lambda: os.getenv("NOTIFY_TG_ENABLED", "false").lower() in ("1", "true", "yes")
    )
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    
    # Slack
    slack_enabled: bool = field(
        default_factory=lambda: os.getenv("NOTIFY_SLACK_ENABLED", "false").lower() in ("1", "true", "yes")
    )
    slack_webhook_url: str = field(default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL", ""))
    
    # Filtering
    min_notional_usd: float = field(
        default_factory=lambda: float(os.getenv("NOTIFY_MIN_NOTIONAL", "100"))
    )
    notify_on_fill: bool = field(
        default_factory=lambda: os.getenv("NOTIFY_ON_FILL", "true").lower() in ("1", "true", "yes")
    )
    notify_on_signal: bool = field(
        default_factory=lambda: os.getenv("NOTIFY_ON_SIGNAL", "false").lower() in ("1", "true", "yes")
    )
    notify_on_risk: bool = field(
        default_factory=lambda: os.getenv("NOTIFY_ON_RISK", "true").lower() in ("1", "true", "yes")
    )
    
    # Rate limiting
    min_interval_sec: int = field(
        default_factory=lambda: int(os.getenv("NOTIFY_MIN_INTERVAL_SEC", "5"))
    )


NotifyLevel = Literal["info", "warning", "error", "success"]


class TradeNotifier:
    """Unified notification service for trading events."""
    
    EMOJI = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "🔴",
        "success": "✅",
        "buy": "🟢",
        "sell": "🔴",
        "money": "💰",
        "chart": "📊",
        "alert": "🚨",
    }
    
    def __init__(self, config: NotificationConfig | None = None):
        """Initialize the notifier.
        
        Args:
            config: Notification configuration (uses env vars if not provided)
        """
        self.config = config or NotificationConfig()
        self._last_notify_ts: float = 0
        self._http_client: httpx.AsyncClient | None = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def notify_fill(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        pnl: float | None = None,
        strategy: str | None = None,
    ) -> bool:
        """Send notification for a trade fill.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            price: Execution price
            quantity: Filled quantity
            pnl: Realized PnL (if closing)
            strategy: Strategy that generated the trade
            
        Returns:
            True if notification was sent
        """
        if not self.config.notify_on_fill:
            return False
        
        notional = price * quantity
        if notional < self.config.min_notional_usd:
            return False
        
        emoji = self.EMOJI["buy"] if side.upper() == "BUY" else self.EMOJI["sell"]
        
        lines = [
            f"{emoji} *Trade Executed*",
            f"• Symbol: `{symbol}`",
            f"• Side: {side.upper()}",
            f"• Price: ${price:,.4f}",
            f"• Quantity: {quantity:,.6f}",
            f"• Notional: ${notional:,.2f}",
        ]
        
        if pnl is not None:
            pnl_emoji = self.EMOJI["money"] if pnl >= 0 else "📉"
            lines.append(f"• PnL: {pnl_emoji} ${pnl:+,.2f}")
        
        if strategy:
            lines.append(f"• Strategy: {strategy}")
        
        lines.append(f"• Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        
        return await self._send("\n".join(lines), "success" if (pnl and pnl >= 0) else "info")
    
    async def notify_signal(
        self,
        symbol: str,
        side: str,
        strength: float,
        strategy: str,
        reason: str = "",
    ) -> bool:
        """Send notification for a strategy signal.
        
        Args:
            symbol: Trading symbol
            side: Signal direction
            strength: Signal strength (0-1)
            strategy: Strategy name
            reason: Signal reason
            
        Returns:
            True if notification was sent
        """
        if not self.config.notify_on_signal:
            return False
        
        emoji = self.EMOJI["chart"]
        strength_bar = "█" * int(strength * 5) + "░" * (5 - int(strength * 5))
        
        lines = [
            f"{emoji} *Strategy Signal*",
            f"• Symbol: `{symbol}`",
            f"• Direction: {side.upper()}",
            f"• Strength: [{strength_bar}] {strength:.0%}",
            f"• Strategy: {strategy}",
        ]
        
        if reason:
            lines.append(f"• Reason: {reason}")
        
        return await self._send("\n".join(lines), "info")
    
    async def notify_risk_alert(
        self,
        alert_type: str,
        message: str,
        level: NotifyLevel = "warning",
    ) -> bool:
        """Send notification for a risk alert.
        
        Args:
            alert_type: Type of risk alert
            message: Alert message
            level: Severity level
            
        Returns:
            True if notification was sent
        """
        if not self.config.notify_on_risk:
            return False
        
        emoji = self.EMOJI["alert"]
        
        lines = [
            f"{emoji} *Risk Alert: {alert_type}*",
            message,
            f"• Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}",
        ]
        
        return await self._send("\n".join(lines), level)
    
    async def notify_daily_summary(
        self,
        total_trades: int,
        total_pnl: float,
        win_rate: float,
        equity: float,
        top_performers: list[tuple[str, float]] | None = None,
    ) -> bool:
        """Send daily trading summary.
        
        Args:
            total_trades: Number of trades
            total_pnl: Total realized PnL
            win_rate: Win rate
            equity: Current equity
            top_performers: List of (symbol, pnl) tuples
            
        Returns:
            True if notification was sent
        """
        pnl_emoji = self.EMOJI["money"] if total_pnl >= 0 else "📉"
        
        lines = [
            f"{self.EMOJI['chart']} *Daily Summary*",
            f"━━━━━━━━━━━━━━━━━━",
            f"• Trades: {total_trades}",
            f"• PnL: {pnl_emoji} ${total_pnl:+,.2f}",
            f"• Win Rate: {win_rate:.1%}",
            f"• Equity: ${equity:,.2f}",
        ]
        
        if top_performers:
            lines.append(f"\n📈 *Top Performers:*")
            for symbol, pnl in top_performers[:3]:
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"  {emoji} {symbol}: ${pnl:+,.2f}")
        
        return await self._send("\n".join(lines), "success" if total_pnl >= 0 else "info")
    
    async def _send(self, message: str, level: NotifyLevel = "info") -> bool:
        """Send notification to all enabled channels.
        
        Args:
            message: Message to send
            level: Notification level
            
        Returns:
            True if at least one channel succeeded
        """
        # Rate limiting
        now = asyncio.get_event_loop().time()
        if (now - self._last_notify_ts) < self.config.min_interval_sec:
            logger.debug("Notification rate limited")
            return False
        self._last_notify_ts = now
        
        results = await asyncio.gather(
            self._send_telegram(message),
            self._send_slack(message, level),
            return_exceptions=True,
        )
        
        success = any(r is True for r in results)
        errors = [r for r in results if isinstance(r, Exception)]
        
        if errors:
            logger.warning(f"Notification errors: {errors}")
        
        return success
    
    async def _send_telegram(self, message: str) -> bool:
        """Send message via Telegram."""
        if not self.config.telegram_enabled:
            return False
        
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            logger.warning("Telegram enabled but credentials not configured")
            return False
        
        try:
            client = await self._get_client()
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            
            response = await client.post(
                url,
                json={
                    "chat_id": self.config.telegram_chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
            
            if response.status_code == 200:
                logger.debug("Telegram notification sent")
                return True
            else:
                logger.warning(f"Telegram error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
    
    async def _send_slack(self, message: str, level: NotifyLevel = "info") -> bool:
        """Send message via Slack webhook."""
        if not self.config.slack_enabled:
            return False
        
        if not self.config.slack_webhook_url:
            logger.warning("Slack enabled but webhook URL not configured")
            return False
        
        # Map level to Slack color
        colors = {
            "info": "#2196F3",
            "warning": "#FF9800",
            "error": "#F44336",
            "success": "#4CAF50",
        }
        
        try:
            client = await self._get_client()
            
            # Convert Markdown to Slack format
            slack_message = message.replace("*", "*").replace("`", "`")
            
            payload = {
                "attachments": [
                    {
                        "color": colors.get(level, "#808080"),
                        "text": slack_message,
                        "mrkdwn_in": ["text"],
                    }
                ]
            }
            
            response = await client.post(
                self.config.slack_webhook_url,
                json=payload,
            )
            
            if response.status_code == 200:
                logger.debug("Slack notification sent")
                return True
            else:
                logger.warning(f"Slack error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False


# Global notifier instance
_notifier: TradeNotifier | None = None


def get_notifier() -> TradeNotifier:
    """Get the global notifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = TradeNotifier()
    return _notifier


async def notify_fill(**kwargs) -> bool:
    """Convenience function to notify on fill."""
    return await get_notifier().notify_fill(**kwargs)


async def notify_signal(**kwargs) -> bool:
    """Convenience function to notify on signal."""
    return await get_notifier().notify_signal(**kwargs)


async def notify_risk_alert(**kwargs) -> bool:
    """Convenience function to notify on risk alert."""
    return await get_notifier().notify_risk_alert(**kwargs)


async def notify_daily_summary(**kwargs) -> bool:
    """Convenience function to send daily summary."""
    return await get_notifier().notify_daily_summary(**kwargs)
