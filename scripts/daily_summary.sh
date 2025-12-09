#!/bin/bash
# Daily Trading Summary Script
# Run via cron or systemd timer

set -e

# Configuration
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-8144814070:AAH4ruTnWt2jEOLGsFoZRTo8sNSmiZhspEw}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-448249054}"
ENGINE_URL="${ENGINE_URL:-http://localhost:8003}"

# Fetch stats from engine
STATS=$(curl -s "$ENGINE_URL/trades/stats" 2>/dev/null || echo '{}')

TRADES=$(echo "$STATS" | jq -r '.total_trades // 0')
WIN_RATE=$(echo "$STATS" | jq -r '.win_rate // 0')
SHARPE=$(echo "$STATS" | jq -r '.sharpe_ratio // 0')
MAX_DD=$(echo "$STATS" | jq -r '.max_drawdown // 0')

# Format percentages
WIN_RATE_PCT=$(printf "%.1f" $(echo "$WIN_RATE * 100" | bc -l 2>/dev/null || echo "0"))
MAX_DD_PCT=$(printf "%.1f" $(echo "$MAX_DD * 100" | bc -l 2>/dev/null || echo "0"))

DATE=$(date -u +"%Y-%m-%d")
TIME=$(date -u +"%H:%M UTC")

# Build message
MSG="📊 *Daily Trading Summary*
📅 $DATE

━━━━━━━━━━━━━━━━━━
📊 Trades: $TRADES
🎯 Win Rate: ${WIN_RATE_PCT}%
📐 Sharpe: $SHARPE
📉 Max DD: ${MAX_DD_PCT}%
━━━━━━━━━━━━━━━━━━

🕐 $TIME"

# Send via Telegram
RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"$TELEGRAM_CHAT_ID\", \"text\": $(echo "$MSG" | jq -Rs .), \"parse_mode\": \"Markdown\"}")

if echo "$RESPONSE" | jq -e '.ok' > /dev/null; then
  echo "✅ Daily summary sent successfully"
else
  echo "❌ Failed to send: $RESPONSE"
  exit 1
fi
