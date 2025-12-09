#!/usr/bin/env python3
"""Daily trading summary script.

Fetches trade statistics from the engine and sends a Telegram notification.
Can be run manually or via cron.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

import httpx

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8144814070:AAH4ruTnWt2jEOLGsFoZRTo8sNSmiZhspEw")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "448249054")
ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8003")
OPS_URL = os.getenv("OPS_URL", "http://localhost:8002")


async def fetch_stats() -> dict:
    """Fetch trading statistics from the engine."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Try engine /trades/stats endpoint
            response = await client.get(f"{ENGINE_URL}/trades/stats")
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        
        try:
            # Fallback to ops /api/metrics/summary
            response = await client.get(f"{OPS_URL}/api/metrics/summary")
            if response.status_code == 200:
                data = response.json()
                return {
                    "total_trades": data.get("totalTrades", 0),
                    "win_rate": data.get("winRate", 0),
                    "total_pnl": data.get("sharpe", 0) * 100,  # Approximate
                    "equity": data.get("balance", 0),
                    "max_drawdown": data.get("maxDrawdown", 0),
                }
        except Exception:
            pass
    
    return {}


async def send_daily_summary():
    """Fetch stats and send daily summary via Telegram."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] Fetching trading stats...")
    
    stats = await fetch_stats()
    
    # Build summary message
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")
    
    total_trades = stats.get("total_trades", 0)
    win_rate = stats.get("win_rate", 0)
    total_pnl = stats.get("total_pnl", 0)
    equity = stats.get("equity", 0)
    max_dd = stats.get("max_drawdown", 0)
    sharpe = stats.get("sharpe_ratio", 0)
    
    # Determine emoji based on performance
    if total_pnl > 0:
        pnl_emoji = "💰"
        header_emoji = "📈"
    elif total_pnl < 0:
        pnl_emoji = "📉"
        header_emoji = "📊"
    else:
        pnl_emoji = "➖"
        header_emoji = "📊"
    
    lines = [
        f"{header_emoji} *Daily Trading Summary*",
        f"📅 {date_str}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"📊 Trades: {total_trades}",
        f"🎯 Win Rate: {win_rate:.1%}",
        f"{pnl_emoji} PnL: ${total_pnl:+,.2f}",
        f"💵 Equity: ${equity:,.2f}",
        f"📉 Max DD: {max_dd:.1%}",
    ]
    
    if sharpe:
        lines.append(f"📐 Sharpe: {sharpe:.2f}")
    
    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        f"🕐 {time_str}",
    ])
    
    message = "\n".join(lines)
    
    # Send via Telegram
    print(f"Sending summary to Telegram...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
        )
        
        if response.status_code == 200:
            print("✅ Daily summary sent successfully!")
            return True
        else:
            print(f"❌ Failed to send: {response.status_code} - {response.text}")
            return False


def main():
    """Main entry point."""
    success = asyncio.run(send_daily_summary())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
