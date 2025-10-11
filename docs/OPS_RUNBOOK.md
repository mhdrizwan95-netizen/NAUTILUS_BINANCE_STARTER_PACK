# OPS Runbook

## Routine Tasks

| Task | Command | Notes |
|------|----------|-------|
| View live PnL dashboard | `open http://localhost:8002/pnl_dashboard.html` | Auto-refresh every 5 s |
| Inspect governance policies | `cat ops/policies.yaml` | Edit & reload automatically |
| Adjust model weights | `curl -X POST /strategy/weights …` | Canary rollout control |
| Check allocations | `cat ops/capital_allocations.json` | Updated every N seconds |
| Pause trading | `export TRADING_ENABLED=false` | Also via governance action |
| Export daily PnL CSV | `python ops/export_pnl.py` | Stored in `ops/exports/` |

## Recovery

1. Stop containers: `docker compose down`
2. Ensure latest snapshot: `engine/state/portfolio.json`
3. Restart: `docker compose up -d`
   The reconciliation daemon auto-restores open orders.

## Troubleshooting

| Symptom | Check | Remedy |
|----------|-------|--------|
| Orders rejected | `engine/logs/orders.jsonl` | Confirm risk rails thresholds |
| Missing metrics | `/metrics` endpoints | Restart Prometheus scraper |
| No SSE updates | `/stream` connection | Check event bus loop in logs |
| Telegram silent | `TELEGRAM_TOKEN`, `CHAT_ID` env vars | Verify API key |
| High latency | `curl -w "@curl-format.txt" /strategy/signal` | Check network/database bottlenecks |
| Memory usage | `docker stats ops` | Restart container if > 2GB |

## Governance Testing

```bash
# Simulate drawdown
python - <<'EOF'
from engine.core.event_bus import BUS
import asyncio
asyncio.run(BUS.publish("metrics.update", {"pnl_unrealized": -150}))
EOF

Watch for [GOV] 📉 Exposure reduced in logs.
```

## Monitoring Dashboards

### Production Metrics Check
```bash
# Overall health
curl http://localhost:8002/status | jq '.engine,.ml'

# Order flow
curl http://localhost:8002/aggregate/metrics | jq '.[] | .orders_submitted_total'

# Capital utilization
curl http://localhost:8002/dash/pnl | jq '.portfolio_summary.total_allocated_percentage'

# Canary promotion status
curl http://localhost:8002/strategy/status | jq '.leaderboard[0]'
```

### Log Analysis
```bash
# Recent errors
tail -n 50 ops/logs/ops.log | grep ERROR

# Order execution times
grep "routing_time" engine/logs/orders.jsonl | tail -20

# Capital allocation changes
tail -f ops/capital_allocations.json | jq '.capital_quota_usd'
```

## Emergency Procedures

### Circuit Breaker Activation
1. **Immediate Pause:**
   ```bash
   curl -X POST http://localhost:8002/kill \
     -H "X-OPS-TOKEN: $(cat .ops_token)" \
     -d '{"enabled": false}'
   ```

2. **Risk Assessment:**
   - Check positions: `engine/state/portfolio.json`
   - Review exposure: `ops/aggregate_exposure.json`
   - Analyze drawdown: `ops/pnl_dashboard.html`

3. **Gradual Resume:**
   ```bash
   # Reduce model weights to 10% of normal
   curl -X POST /strategy/weights -d '{"weights": {"model1": 0.01}}'

   # Slowly scale back up over hours
   curl -X POST /strategy/weights -d '{"weights": {"model1": 0.1}}'
   ```

### Data Corruption Recovery
1. **Stop all services:** `docker compose down`
2. **Backup corrupted files:** `cp -r ops/ backup_$(date +%s)/`
3. **Clean restart:** `docker compose up -d --build`
4. **Validate restoration:** Check latest PnL export matches expectations

### Market Disruption Response
1. **Increase cooldowns:** Edit `capital_policy.json` to extend allocation freeze
2. **Switch to conservative models:** Adjust `strategy_weights.json` to favor stable strategies
3. **Reduce position sizes:** Update `MIN_NOTIONAL_USDT` in engine configs
4. **Monitor closely:** Enable high-frequency alerting

## Performance Tuning

### Throughput Optimization
```yaml
# ops/policies.yaml - increase concurrency
max_concurrent_signals: 50
worker_threads: 8
signal_queue_size: 1000
```

### Memory Optimization
```yaml
# Limit metrics history
metrics_retention_hours: 24
allocation_history_limit: 100

# Reduce dashboard polling frequency
dashboard_refresh_sec: 10
```

### Latency Optimization
- Enable HTTP/2 if available
- Use Redis for event bus (SSE fallback)
- Pre-warm price caches
- Optimize Prometheus queries

## Backup & Restore

### State Backup
```bash
# Daily backup of critical state
tar -czf backup_$(date +%Y%m%d).tar.gz \
  ops/strategy_registry.json \
  ops/capital_allocations.json \
  engine/state/ \
  ops/logs/*.jsonl
```

### Disaster Recovery
```bash
# From recent backup
docker compose down
tar -xzf recent_backup.tar.gz
docker compose up -d

# Validate
curl http://localhost:8002/status | jq '.state.recovered'
```

## Capacity Planning

### Scaling Signals
- Current: 100 signals/minute
- Threshold: 500 signals/minute (scale OPS horizontally)

### Scaling Metrics
- Current: 50 venues × 10 models = 500 time series
- Threshold: 5000 time series (upgrade Prometheus)

### Scaling Storage
- Current: 5GB/day logs
- Threshold: 50GB/day (implement log rotation/compression)

## Security Checklist

- [ ] API tokens rotated monthly
- [ ] SSH keys updated quarterly
- [ ] Environment files encrypted at rest
- [ ] Network firewall rules current
- [ ] Audit logs backed up securely
- [ ] Container images vulnerability scanned
