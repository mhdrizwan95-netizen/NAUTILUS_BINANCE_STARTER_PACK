🧭 Dashboard v2 Data Flow Architecture

                ┌────────────────────────────────────────────┐
                │               Strategy Core                │
                │────────────────────────────────────────────│
                │ strategies/hmm_policy/strategy.py           │
                │ ml_service/app.py  → emits {state,action,confidence} │
                └──────────────┬─────────────────────────────┘
                               │
                               ▼
                   ┌──────────────────────────┐
                   │  telemetry.py (M14–M16)  │
                   │──────────────────────────│
                   │ Prometheus metrics        │
                   │  • state_active           │
                   │  • pnl_realized/unrealized│
                   │  • drift_score            │
                   │  • policy_confidence ★    │
                   │  • order_fill_ratio ★     │
                   │  • venue_latency_ms ★     │
                   │  • m19_actions_total ★    │
                   │  • m20_incidents_total ★  │
                   └──────────────┬───────────┘
                                  │  scrape / push
                                  ▼
           ┌──────────────────────────────────────────────────────────────┐
           │                        Ops Layer                             │
           │──────────────────────────────────────────────────────────────│
           │ ops/ops_api.py – REST control plane                          │
           │   GET  /status         → runtime state                        │
           │   GET  /artifacts/m15  → calibration gallery (M15)            │
           │   GET  /lineage        → memory lineage (M21)                 │
           │   POST /kill           → kill-switch (M20)                    │
           │   POST /retrain        → trigger M15 retrain                  │
           │   POST /canary_promote → blue/green promotion (M11)           │
           │   POST /flush_guardrails → optional reset                     │
           │                                                              │
           │ ops/m19_scheduler.py  → calls telemetry.inc_scheduler_action()│
           │ ops/m20_playbook.py   → calls telemetry.inc_guardian_incident()│
           │ ops/m23_heartbeat.py  → pushes lineage & calibration to WS    │
           └──────────────┬────────────────────────────────────────────────┘
                          │ REST + WebSocket
                          ▼
          ┌──────────────────────────────────────────────────────────────┐
          │                     Dashboard Backend (FastAPI)               │
          │──────────────────────────────────────────────────────────────│
          │ dashboard/app.py                                             │
          │   Gauges mirror telemetry metrics                            │
          │   REST:                                                      │
          │     /api/metrics_snapshot → small JSON for live strip        │
          │     /api/artifacts/m15     → proxy to ops_api                │
          │     /api/lineage           → proxy to ops_api                │
          │   WS Topics:                                                 │
          │     /ws/scheduler   ← from M19                               │
          │     /ws/guardian    ← from M20                               │
          │     /ws/lineage     ← from M23 heartbeat                     │
          │     /ws/calibration ← from M23 heartbeat                     │
          └──────────────┬───────────────────────────────────────────────┘
                         │ WebSocket + REST
                         ▼
         ┌──────────────────────────────────────────────────────────────┐
         │                     Dashboard UI (Next.js App)               │
         │──────────────────────────────────────────────────────────────│
         │  Live Strip Card ← /api/metrics_snapshot                     │
         │  PnL / Exposure Card ← Prometheus stream                     │
         │  Policy Confidence Gauge ← policy_confidence                 │
         │  Guardrails Heatmap ← /metrics guardrail_trigger_total       │
         │  Scheduler Feed ← ws/scheduler                               │
         │  Guardian Feed ← ws/guardian                                 │
         │  Lineage Panel ← ws/lineage (+ /api/lineage)                 │
         │  Calibration Gallery ← ws/calibration (+ /api/artifacts/m15) │
         └──────────────────────────────────────────────────────────────┘


⸻

🔁 Operational Loop (Heartbeat Summary)

Module	Cycle	Purpose
ml_service/app.py	tick ≈ 1 s	Predict → update telemetry metrics
ops/m19_scheduler.py	event-driven	Action execution + increment counter
ops/m20_playbook.py	incident-driven	Log guardian response + counter
ops/m23_heartbeat.py	every 10 s	Broadcast lineage + calibration
dashboard/app.py	continuous	Expose metrics + relay WebSockets
Next.js frontend	realtime	Animate tiles + display telemetry


⸻

✨ Outcome
	•	Every dashboard tile now has a live data source.
	•	Guardian and Scheduler incidents stream instantly.
	•	Lineage and calibration visuals refresh automatically.
	•	/metrics, /api/*, and /ws/* form a clean, decoupled contract.

⸻

📘 Module Responsibilities Summary

Module	Role	Key Functions
M14 – Telemetry	Metric instrumentation	Defines Prometheus Gauges & Counters (state_active, pnl_*, drift_score, etc.)
M15 – Calibration	Model calibration routines	Runs calibrate_policy.py, generates reward heatmap & policy boundary PNGs.
M16 – Reinforce	Policy reinforcement	Computes rolling reward, entropy, and win-rate metrics; logs to Prometheus.
M18 – Portfolio Risk	Multi-symbol covariance & risk	Tracks corr_btc_eth, port_vol, and cluster-based volatility allocations.
M19 – Scheduler	Action orchestrator	Determines when to retrain, promote, or halt; increments m19_actions_total.
M20 – Guardian	Safety & recovery reflexes	Executes kill-switches and health playbooks; logs m20_incidents_total.
M21 – Memory Manager	Model lineage archiving	Maintains lineage_index.json, snapshots model generations and KPIs.
M22 – Comms Service	Cross-module coordination	Summarizes lineage and incident data for other ops layers.
M23 – Heartbeat	Dashboard pulse	Broadcasts lineage and calibration updates every 10s via WebSocket.
M24 – Collective Hub	Peer aggregation	Aggregates metrics across multiple nodes or instances for global insight.
M25 – Governor	Compliance and control logic	Oversees system-wide violations and triggers trading disablement.

This table acts as a quick-glance operational index for engineers and operators maintaining the Nautilus ecosystem.