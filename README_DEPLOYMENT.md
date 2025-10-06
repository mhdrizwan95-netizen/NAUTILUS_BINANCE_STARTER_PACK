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
