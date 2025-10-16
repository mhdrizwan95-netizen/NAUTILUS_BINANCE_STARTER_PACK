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
The Ops API exposes:

- `GET /readyz` — readiness signal used by container healthchecks.
- `GET /healthz` — lightweight liveness endpoint.
- `GET /aggregate/health` — summarized health of engines and collectors.

Engines provide `GET /health` and `/metrics`.

#### Control & Auth
The following Ops endpoints require `X-OPS-TOKEN` with the value of `OPS_API_TOKEN` (default: `dev-token`):

- `POST /kill` — pause/resume trading globally.
- `POST /strategy/weights` — adjust rollout weights.
- `POST /retrain`, `POST /canary_promote` — model lifecycle hooks.

#### Metrics Plumbing

* OPS runs multiple Uvicorn workers (`OPS_WORKERS`, default `2`). Every collector registers against the shared registry in `ops/prometheus.py` to remain multiprocess-safe.
* Metrics live under `/metrics` on each service (`http://localhost:8002/metrics`, `http://localhost:8003/metrics`, etc.).
* Histogram families use standard `_bucket`, `_count`, `_sum` names (`submit_to_ack_ms_bucket` for order latency).

Key environment variables:

- `PROMETHEUS_MULTIPROC_DIR` — shared directory for multiprocess shards (defaults to `/tmp/prom_multiproc` in the container; created and chowned in the Dockerfile).
- `OPS_WORKERS` — number of Uvicorn workers for the Ops API.
- `OPS_METRICS_PORT` — exported host port for scraping (default `9102`, but Prometheus scrapes the HTTP endpoint on `8002`).

#### Observability Bundle

Located in `ops/observability/`:

1. Start the trading stack: `docker compose up -d`.
2. Launch the observability pack:
   ```bash
   cd ops/observability
   docker compose -f docker-compose.observability.yml up -d
   ```
3. Prometheus (http://localhost:9090) scrapes:
   - `hmm_ops:8002`
   - `engine_binance:8003`
   - `engine_bybit:8003`
   - `engine_ibkr:8003`
   - `ml_service:8010` (optional)
4. Grafana (http://localhost:3000, admin/admin) auto-loads the “HMM • Trading Overview” dashboard from `grafana/dashboards/hmm_trading_overview.json`.

If you run the observability stack on a remote host, ensure the project network name in `docker-compose.observability.yml` matches the main compose project (`docker network ls`).

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
	•	`docker compose ps` — confirm `hmm_engine_*` and `hmm_ops` are healthy.  
	•	Ensure `./data` remains mounted for snapshots, lineage, and calibration artifacts.  
	•	`curl http://localhost:8002/metrics` — verify Prometheus exposition for collectors.  
	•	If observability is enabled, check Grafana’s “HMM • Trading Overview” dashboard loads without scrape errors.

### Engine-Driven Order Flow (Current)
- Use venue-specific engines for low-level order placement (e.g. `http://localhost:8003/orders/market` for Binance testnet).
- Ops API (`http://localhost:8002`) exposes aggregated snapshots (`/account_snapshot`, `/aggregate/portfolio`) and governance controls (`/strategy/weights`, `/kill`).
- Front-end dashboards (served from Ops) read the Ops metrics registry so Equity, Exposure, and PnL tiles reflect the engines’ source of truth.

Smoke test:
```bash
docker compose up -d --build
curl -X POST http://localhost:8003/orders/market \
  -H "content-type: application/json" \
  -d '{"symbol":"BTCUSDT.BINANCE","side":"BUY","quote":50}'
curl -s http://localhost:8002/account_snapshot | python -m json.tool
```
