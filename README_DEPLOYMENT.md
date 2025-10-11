Calibration Notebook: see notebooks/M15_Calibration.ipynb for M15 reward/online-learning diagnostics.

### Calibration Utilities

#### M15 Calibration (FAST)
Run a quick backtest to generate feedback, then produce calibration PNGs:
    ./ops/calibrate_fast.sh
Outputs → data/processed/calibration/*.png

#### M15 Calibration (PAPER)
Run paper trading on testnet for 15 minutes, then calibrate:
    ./ops/calibrate_paper.sh 900
Set BINANCE_IS_TESTNET=true and TRADING_ENABLED=true in your environment or .env.

#### M15: Headless calibration (requires existing feedback_log.csv)
Run: `python ops/calibrate_policy.py`
Outputs → `data/processed/calibration/{reward_heatmap.png, policy_boundary.png, rolling_winrate.png}`

### M16 Reinforcement Fine-Tuning
Refines the policy using recency-weighted, risk-adjusted rewards and off-policy correction.

Run:
    ./ops/m16_reinforce.sh

Flow:
    feedback_log.csv → m16_reinforce.py → policy_vNext.joblib → canary_sim → /promote

Outputs:
    data/processed/m16/{learning_curve.png, drift_vs_reward.png, metrics.prom}
Grafana:
    Scrape metrics.prom (file_sd or sidecar) to plot m16_avg_reward, m16_entropy, m16_winrate.

### M20 Resilience & Self-Healing
Guardian daemon monitors live metrics for anomalies and executes mitigation playbooks.

Run:
    ./ops/m20_guardian.sh 60

Playbooks:
- drawdown → halve risk temporarily
- guardrail_spike → reset guardrails + throttle trading
- exchange_lag → restart exchange connector
- entropy_spike → reduce exposure
Logs: data/processed/m20/{incident_log.jsonl, recovery_actions.jsonl}

### M21 Memory & Lineage
Archives complete evolutionary lineage with performance tracking.

Run once:
    python ops/m21_memory_manager.py

Daemon:
    ./ops/m21_memory_daemon.sh 600

Visualize lineage:
    python ops/m21_memory_viz.py

Artifacts:
    data/memory_vault/lineage_index.json
    data/memory_vault/*/metadata.json
    data/memory_vault/lineage_graph.png

### M22 Communication & Expression Layer
FastAPI microservice exposes organism state and sends alerts to chat platforms.

Run API:
    uvicorn ops.m22_comms_service:APP --port 8080

Endpoints:
    /status       → Current organism status and last decisions
    /decisions    → Last scheduler action
    /alert (POST) → Push manual or system alerts

Environment:
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK

Notification utility:
    python ops/m22_notify.py --message "Custom alert" --severity critical
    python ops/m22_notify.py --incident  # Send last incident

### M23 Dreaming Mode
Offline imagination system that tests historical or synthetic market scenarios.

Run once:
    python ops/m23_dream_engine.py

Daemon:
    ./ops/m23_dream_daemon.sh 1800

Visualize dream history:
    python ops/m23_dream_viz.py

Outputs:
    data/dreams/*.json (dream records)
    data/dreams/dream_timeline.png
    data/dreams/dream_distributions.png
    data/dreams/dream_generations.png
    data/dreams/dream_insights.json

### M24 Collective Intelligence
Enables multiple organisms to share anonymized learning metrics through a central hub.

Run hub:
    uvicorn ops.m24_collective_hub:APP --port 8090

Run peer daemon on each node:
    COLLECTIVE_HUB=http://hub-ip:8090 ./ops/m24_peer_daemon.sh 900

Data:
    data/collective/submissions.jsonl   # incoming summaries
    data/collective/aggregate.json      # consensus metrics
    data/collective/consensus.json      # local copy of aggregate

### M25 Ethical Governor
Applies hard policy constraints and human oversight to prevent unintended behavior.

Run checks:
    python ops/m25_governor.py

Config:
    ops/m25_policy.yaml (risk caps, human-review policy)

If violations occur:
    TRADING_ENABLED=false is set and compliance_log.jsonl updated.

Optional:
    python ops/m25_approval.py  → sends email for manual approval before promotion.

### Dashboard Health & Observability

#### Health Endpoints
The Ops API provides health checking endpoints:

- `/healthz` - Fast liveness check, always returns `{"ok": true}`
- `/readyz` - Readiness check that verifies data sources are available

#### Environment Variables
- `OPS_API_TOKEN` - Token for authenticating control actions (kill, retrain, canary_promote). Default: "dev-token"
- `DASH_POLL_MS` - Dashboard polling interval in milliseconds. Default: 5000 (5 seconds)
- `PROM_METRIC_KEYS` - CSV of additional Prometheus metric names to extend PROM_MAP. Default: none

#### Metrics Fallback Chain
Dashboard auto-preferences metrics from multiple sources in this priority order:

1. **ops_snapshot** - Ops API `/metrics_snapshot` (POST/PUT from strategy)
2. **ops_metrics** - Ops API `/metrics` (JSON with pnl/policy/execution structure)
3. **ops_split** - Ops API `/pnl` and `/state` / `/states` endpoints
4. **ops_prom** - Ops API `/metrics` parsed as Prometheus exposition format
5. **legacy** - Fallback to zeros if all sources fail

Each source provides the `source` indicator in the dashboard response for observability.

#### Authenticated Control Actions
Control endpoints require `X-OPS-TOKEN` header:
- `POST /kill` - Enable/disable trading
- `POST /retrain` - Trigger ML retraining
- `POST /canary_promote` - Promote canary models

#### UI Guardrails
Live Strip shows visual indicators:
- Red outline: drift_score > 0.8
- Green background: policy_confidence > 0.7
- Amber background: venue_latency_ms > 200ms

#### Docker Healthchecks
Ops container healthcheck uses `/readyz` endpoint for service coordination.

### M18 Multi-Symbol Mode
To activate shared risk allocation:
    import risk.covariance_allocator as cov
    allocator = cov.CovarianceAllocator(window=500, target_var=0.0001)
    strategy.enable_covariance_allocator(allocator)
Diagnostics:
    python ops/m18_cov_diag.py

### M19 Meta-Learning Scheduler
Policy-driven orchestrator that triggers M15/M16/M17/M18 based on live KPIs.

Run once:
    ./ops/m19_run_once.sh
Daemon (every 5 min):
    ./ops/m19_daemon.sh 300

Config:
    ops/m19_scheduler.yaml (thresholds, cooldowns, safeguards, priorities)

State & Logs:
    data/processed/m19/scheduler_state.json
    data/processed/m19/metrics_snapshot.json (input KPIs)

Final ops checklist
	•	Docker stack: make up / make logs.
	•	Data path: keep dropping lineage/calibration into ./data/** (containers see them live).
	•	Metrics: when Ops adds /metrics_snapshot, the dashboard will auto-prefer it.

	•	/api/metrics_snapshot on 8002 returns zeros ➜ your shim is working, but 8001 (Ops) has no metrics endpoints (/metrics_snapshot, /metrics, /pnl, /state(s) all 404).
	•	The zsh: number expected / command not found: # lines are from pasting comments. No harm—just noise.

### Engine-Driven Order Flow (New)
- Service `engine` (port **8003**) owns Binance testnet order submission and maintains the canonical portfolio snapshot.
- Ops API (`8001`) proxies `/orders/market` to the engine and mirrors its `/portfolio` in `/account_snapshot` and metrics snapshots.
- Dashboard (`8002`) now reads `ops_snapshot` so Cash, Equity, Exposure and PnL tiles reflect the engine’s source of truth.

Smoke test:
```bash
docker compose up -d --build
curl -X POST http://localhost:8003/orders/market \
  -H "content-type: application/json" \
  -d '{"symbol":"BTCUSDT.BINANCE","side":"BUY","quote":50}'
curl -s http://localhost:8001/account_snapshot | python -m json.tool
```
