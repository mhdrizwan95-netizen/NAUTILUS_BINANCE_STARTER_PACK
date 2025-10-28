#!/bin/bash
# verify_fill_chain.sh
# Requires: `jq`, `docker compose` and HTTP API accessible

SYMBOL="ETHUSDT.BINANCE"
QTY=0.010

echo "Submitting market SELL of $QTY $SYMBOL …"
RESP=$(curl -s -X POST "http://localhost:8003/orders/market" \
  -H 'Content-Type: application/json' \
  -d "{\"symbol\":\"$SYMBOL\",\"side\":\"SELL\",\"quantity\":$QTY,\"newOrderRespType\":\"RESULT\"}")

echo "Response: $RESP" | jq .

ORDER_ID=$(echo "$RESP" | jq -r '.orderId')
echo "Order ID: $ORDER_ID"

echo "Waiting 15 seconds for fill & processing …"
sleep 15

echo "Fetching logs for fill/refresh/stopval for Order ID $ORDER_ID:"
docker compose logs engine_binance --since=30s | egrep -i "ORDER_REFRESH|trade\.fill|STOPVAL.*$ORDER_ID"

echo "Fetching metrics for symbol $SYMBOL:"
curl -s http://localhost:9103/metrics | egrep "position_amt\{symbol=\"$SYMBOL\"|stop_validator_(missing|repaired)_total|health_state"

echo "Verification complete."