#!/usr/bin/env bash
set -euo pipefail

PROM_URL="${PROM_URL:-http://localhost:9090}"
# Include all dashboard-used metrics from your extracted queries
METRICS=${METRICS:-"equity_usd exposure_usd orders_placed_total pnl_realized_total trading_enabled max_notional_usdt trading:pnl_realized_usd"}
RANGE_MINUTES=${RANGE_MINUTES:-60}

# Portable timestamp generation using python with timezone awareness
START=$(python3 -c "import datetime; now=datetime.datetime.now(datetime.UTC); print((now - datetime.timedelta(minutes=${RANGE_MINUTES})).isoformat())")
END=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.UTC).isoformat())")

jq -n --arg start "$START" --arg end "$END" '{start:$start,end:$end,metrics:[]}' > /tmp/_labels_dump.json

for M in $METRICS; do
  # Pull all series for this metric in the window using properly encoded request
  resp=$(curl -fsS -G "${PROM_URL}/api/v1/series" --data-urlencode "match[]=${M}{ }" --data-urlencode "start=$START" --data-urlencode "end=$END")
  # Produce: {metric:"equity_usd", labels: {job:[...], instance:[...], symbol:[...], ...}}
  block=$(echo "$resp" | jq --arg m "$M" '
    .data
    | (map(keys) | add | unique) as $allKeys
    | {
        metric: $m,
        labels: (reduce $allKeys[] as $k (
          {};
          .[$k] = ( [ .data[]? | .[$k] ] | unique | sort | map(select(.!=null)) )
        ))
      }
  ')
  jq --argjson block "$block" '.metrics += [$block]' /tmp/_labels_dump.json > /tmp/_labels_dump.json.next
  mv /tmp/_labels_dump.json.next /tmp/_labels_dump.json
done

out="prom_label_inventory.json"
mv /tmp/_labels_dump.json "$out"
echo "Wrote $out (window ${RANGE_MINUTES}m) from ${PROM_URL}"
