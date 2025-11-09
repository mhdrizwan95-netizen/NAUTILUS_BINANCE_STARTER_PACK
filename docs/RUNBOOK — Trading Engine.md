

RUNBOOK — Trading Engine (Docker Compose, Local → VPS)

Audience: operators and developers
Scope: how to run, observe, pause, recover, and gradually scale the trading system implemented under engine/, ops/, router/, with BUS events, guards, and observability.

⸻

1) Purpose & What Lives Here

This stack is a feature-gated, risk-managed crypto trading system with:
	•	engine/ — strategies, risk rails, handlers, feeds, guards, telemetry loops
	•	router/ (under engine/core/) — order routing, maker/taker logic, slippage audit
	•	BUS — event bus for decoupled publish/subscribe
	•	ops/ — Telegram, digest, health notify, Grafana dashboards, WS runners
	•	metrics — Prometheus counters/gauges/histograms

Almost every feature is toggleable by env flags, with safe defaults and instant rollback via flag off.

⸻

2) System Overview (mental map)
	•	Strategies
	•	engine/strategies/event_breakout.py — listing/event play, half-size window, SL/TP ladder + trailing loop
	•	Risk & Safety
	•	engine/risk_guardian.py — daily stop, dual-health gate, auto re-arm at boundary
	•	engine/ops/stop_validator.py — server-side stop validator/repair
	•	engine/guards/depeg_guard.py — USDT peg monitor (safe-mode)
	•	engine/guards/funding_guard.py — funding spike trims (+ optional hedge)
	•	engine/execution/venue_overrides.py — auto size-cutback & scalp-mute (TTL)
	•	engine/risk/sizer.py — ATR% risk-parity sizer (optional)
	•	Feeds & Events
	•	engine/feeds/binance_announcements.py → handler → strategy.event_breakout
	•	engine/ops/fills_listener.py + engine/core/order_router.py → BUS trade.fill
	•	Observability
	•	Prom metrics (see engine/metrics.py)
	•	Telegram: ops/notify/telegram.py, digest (engine/ops/digest.py), health notify (engine/ops/health_notify.py)
	•	Grafana dashboards under ops/observability/grafana/dashboards/

⸻

3) Start Here: Operator Checklist (Local, Docker Compose)

Before first run
	•	Ensure TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID are set (for daily digest & alerts).
	•	Confirm time sync (NTP) and system clock correct.
	•	Confirm API keys are trade-only, withdrawals disabled.

For a standard limited-live session
	•	Set flags (no secrets) in your Compose env file; ensure:
	•	Enabled:
	•	EVENT_BREAKOUT_ENABLED=true, EVENT_BREAKOUT_DRY_RUN=false, EVENT_BREAKOUT_HALF_SIZE_MINUTES=5
	•	STOP_VALIDATOR_ENABLED=true, STOP_VALIDATOR_REPAIR=true
	•	AUTO_CUTBACK_ENABLED=true
	•	RISK_PARITY_ENABLED=true
	•	DEPEG_GUARD_ENABLED=true (with DEPEG_EXIT_RISK=false to start)
	•	FUNDING_GUARD_ENABLED=true (with FUNDING_HEDGE_RATIO=0.00)
	•	TELEGRAM_ENABLED=true, EVENT_BREAKOUT_METRICS=true
	•	Disabled (initially):
	•	DEX_EXEC_ENABLED=false
	•	SCALP_MAKER_SHADOW=true (shadow only) or maker off

On start, verify
	•	Telegram sends a daily digest after first window.
	•	Grafana shows data flowing in:
	•	“Event Breakout – KPIs”
	•	“Execution – Slippage Heatmap”
	•	health_state gauge is 0 (OK); no DEGRADED/HALTED flapping.

If any of those fail, do not trade live; flip EVENT_BREAKOUT_DRY_RUN=true and investigate.

⸻

4) Run Modes (how we operate)
	•	Dry-Run: orders are not placed; strategies publish plans/metrics only. Use for wiring checks and dashboards.
	•	Limited Live: tiny sizes, strict caps, all guards enabled. Default for initial rollout and after code changes.
	•	Full Live: sizes increased per weekly review after passing acceptance criteria.

⸻

5) Flags Reference (grouped)

Core Trading
	•	EVENT_BREAKOUT_ENABLED, EVENT_BREAKOUT_DRY_RUN, EVENT_BREAKOUT_HALF_SIZE_MINUTES, EVENT_BREAKOUT_SIZE_USD
	•	RISK_PARITY_ENABLED, RISK_PARITY_TF, RISK_PARITY_N, RISK_PARITY_MIN_NOTIONAL_USD, RISK_PARITY_MAX_NOTIONAL_USD
	•	WARMUP_SEC (entry block after start)
	•	MIN_NOTIONAL_BLOCK_USD (block too-small orders)

Risk & Guards
	•	Guardian: GUARDIAN_ENABLED, MAX_DAILY_LOSS_USD, DAILY_RESET_TZ, DAILY_RESET_HOUR
	•	Depeg: DEPEG_GUARD_ENABLED, DEPEG_THRESHOLD_PCT, DEPEG_CONFIRM_WINDOWS, DEPEG_ACTION_COOLDOWN_MIN, DEPEG_EXIT_RISK, DEPEG_SWITCH_QUOTE
	•	Funding: FUNDING_GUARD_ENABLED, FUNDING_SPIKE_THRESHOLD, FUNDING_TRIM_PCT, FUNDING_HEDGE_RATIO
	•	Validator: STOP_VALIDATOR_ENABLED, STOP_VALIDATOR_GRACE_SEC, STOP_VALIDATOR_INTERVAL_SEC, STOP_VALIDATOR_REPAIR, STOP_VALIDATOR_REPAIR_TP
	•	Overrides: AUTO_CUTBACK_ENABLED, AUTO_CUTBACK_SIZE_MULT, AUTO_MUTE_SCALP_THRESHOLD, spread/TTL knobs in venue_overrides.py

Observability & Ops
	•	TELEGRAM_ENABLED, HEALTH_TG_ENABLED, HEALTH_DEBOUNCE_SEC
	•	EVENT_BREAKOUT_METRICS, DIGEST_INTERVAL_MIN, DIGEST_6H_ENABLED
	•	TELEGRAM_BRIDGE_ENABLED (relay notify.telegram)
	•	EXEC_FILLS_LISTENER_ENABLED, WS_HEALTH_ENABLED, WS_DISCONNECT_ALERT_SEC

Experimental (flip cautiously)
	•	Maker real posting for scalps (symbol-gated in router)
	•	DEX_EXEC_ENABLED with strict slippage/gas caps and 1 live position cap

⸻

6) Normal Ops: What “healthy” looks like

Dashboards
	•	KPIs: Live plans vs trades stable; half-size applies in first 5 minutes post-listing.
	•	Slippage heatmap: Few or no chronic offenders; histogram shows most fills within ~5–10 bps on majors.

Telegram
	•	One digest per day
	•	Health pings only for: WS reconnects, depeg triggers/rearms, daily stop fires/re-arms.

Metrics to glance at
	•	event_bo_trades_total increasing sanely
	•	stop_validator_missing_total low; stop_validator_repaired_total not spiking
	•	health_state==0 most of the time

⸻

7) When to Pause (Kill-Switch)

Pause immediately if any of:
	•	health_state is 2 (HALTED) or remains 1 (DEGRADED) > 5 minutes.
	•	Daily stop triggers unexpectedly early in session.
	•	Stop validator reports repeated missing SL after fills.

Action: Set trading flag off (the guardian or ops helper does this); confirm Telegram shows HALTED. Resume only after cause is understood and fixed; on resume, emit health.state=0.

⸻

8) Rollout Timeline (local → stable live)

Day 0–1 — Observation
	•	Live Event Breakout at tiny size; stop validator repair on; cutback/mute on; risk-parity on.
	•	Acceptance to move forward:
	•	Avg taker slippage (futures scalps) ≤ 10 bps over last 6h
	•	stop_validator_repaired_total ≤ 3/day
	•	No sustained DEGRADED/HALTED

Day 2–3 — Maker A/B
	•	Enable maker only for ETHUSDT (futures, intent=SCALP).
	•	Acceptance:
	•	Maker hit ratio ≥ 35%
	•	Maker p50 fill time ≤ 500 ms
	•	Win-rate delta vs BTC taker not worse than −2pp
	•	If fails: revert ETH to taker immediately.

Day 3–4 — Chaos drills
	•	Simulate WS drop (90s): entries pause, exits unaffected; single health ping.
	•	Simulate USDT depeg (mock): trading paused, optional de-risk dry-run; clear re-arm path.

Day 5–7 — Guards live
	•	Flip DEPEG_EXIT_RISK=true, then FUNDING_HEDGE_RATIO=0.30 if trims were clean.
	•	Nightly denylist refresh from entropy & offenders.

⸻

9) Recovery & Rollback

Soft rollback (preferred): turn off the feature flag that introduced risk (maker/DEX/announcement trade sizing) → system continues on safe defaults.

Hard pause: set trading flag off (guardian will respect), verify BUS health.state=2 (HALTED); keep validator and SLs running.

Re-arm: once cause fixed, set trading flag true; system emits health.state=0 (OK) at daily boundary or manual helper.

If WS is unstable: keep listener off (EXEC_FILLS_LISTENER_ENABLED=false); router still emits fills for immediate protection checks.

⸻

10) Weekly Review (evidence → action)
	•	Export expectancy by strategy/intent; trade count thresholds for statistical relevance.
	•	Compare maker vs taker slippage and win rate by symbol; toggle maker per-symbol accordingly.
	•	Feed offender symbols to conf/event_denylist.txt (and SIGHUP reload) or reduce size via overrides.
	•	Adjust size_usd for Event Breakout based on efficiency (trades/live plans) and skip rates.

⸻

11) VPS Migration Notes (when ready)
	•	Stateful paths to persist: state/ (quarantine, trading flag, VAR artifacts), logs/
	•	Time: NTP + correct TZ; guardian uses DAILY_RESET_TZ/HOUR
	•	Service: Docker Compose or systemd; ensure graceful restart retains state/ volume
	•	Secrets: inject via env or secrets manager; never commit keys
	•	Networking: keep Prom & Grafana reachable; Telegram egress open

⸻

12) Known Good Alerts
	•	Depeg Triggered → HALTED, manual review required; re-arm emits OK.
	•	Funding Spike → trim logged; if hedge enabled, BTC hedge placed (verify).
	•	Stop Repaired → one Telegram line via notify bridge; if repeated for same symbol, auto-deny for a block.

⸻

13) Appendix — Quick Interp of Key Metrics
	•	event_bo_plans_total{dry/live} — plan activity; large dry with tiny live → guardrails too strict or listings weak
	•	event_bo_skips_total{reason} — pressure points (late_chase, spread, notional, slippage)
	•	exec_slippage_bps{symbol,venue,intent} — distribution of fill quality
	•	stop_validator_missing_total / ...repaired_total — safety net status
	•	health_state — 0 OK, 1 DEGRADED, 2 HALTED
	•	risk_depeg_active — 1 during safe-mode window

⸻

14) One-Page “What do I do?” (pin this)
	1.	See HALTED or weird PnL?
	•	Kill-switch (trading flag off).
	•	Check Telegram health reason + Grafana KPIs.
	•	Confirm server-side SLs exist (validator logs).
	•	Fix root cause → re-arm (OK emitted).
	2.	Slippage spikes or maker misses?
	•	Auto size-cutback/mute should kick in.
	•	If not, disable maker on that symbol (router per-symbol gate).
	•	Add to denylist if symptomatic across days.
	3.	Listings choppy?
	•	Increase half-size window; tighten late-chase/ spread guardrails.
	•	Watch skips by reason; if >30% late_chase, scale down event size.
	4.	USDT wobbly or funding high?
	•	Depeg guard HALTED → review; if mild, keep entries off for window.
	•	Funding guard trims; enable hedge once trims are clean.

⸻
