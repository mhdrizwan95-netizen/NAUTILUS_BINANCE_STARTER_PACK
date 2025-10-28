# Post-Integration Stabilization Checklist

## Stage A – Acceptance Criteria & Baseline
- [ ] `strategy_leverage_mismatch_total` remains `0` across ≥24 h sandbox run.
- [ ] Signal-to-order latency (`strategy_signal_latency_seconds`) p50 < 150 ms, p95 < 400 ms.
- [ ] Bucket usage metrics never exceed configured allocation +2 % headroom.
- [ ] Order failure/rejection rate < 0.5 %.
- [ ] No unhandled exceptions in runtime logs for ≥24 h.
- [ ] Audit trail captures config changes and leverage actions without gaps.

## Stage B – Staging / Synthetic Run (48 h)
- [ ] Run synthetic harness or testnet profile for continuous 48 h.
- [ ] Verify `strategy_leverage_configured` equals `strategy_leverage_applied` for all symbols.
- [ ] Confirm bucket lock/unlock cycles complete; no stale margin fractions.
- [ ] Review Prometheus/Grafana dashboards for leverage, bucket, and queue metrics.
- [ ] Export and archive logs + metrics snapshots for post-run analysis.

Gate: All Stage A + Stage B items checked before moving to canary.

## Stage C – Canary / Dry Run (24 h)
- [ ] Deploy to live sub-account (or shadow mode) with ≤2 % capital allocation.
- [ ] Validate real Binance `/fapi/v1/leverage` responses match config.
- [ ] Monitor live fills for correct leverage & sizing; no unexpected liquidation margin usage.
- [ ] Ensure alerting (mismatch, bucket overuse, error spikes) is active and quiet.
- [ ] Compare realized vs expected PnL exposure and queue latency.

Gate: No critical alerts, metrics within thresholds, reviewed by owner(s).

## Stage D – Full Deployment
- [ ] Promote release with feature toggle (if available) and document version.
- [ ] Enable full-capital trading once canary metrics validated.
- [ ] Monitor dashboards hourly for first 24 h, daily afterwards for one week.
- [ ] Hold daily standup review; log any anomalies and resolutions.
- [ ] Keep rollback plan ready (previous release + config snapshot).

## Stage E – Regression & Maintenance
- [ ] Schedule nightly synthetic harness run covering leverage paths.
- [ ] Ensure leverage/unit tests integrated into CI.
- [ ] Weekly review of leverage metrics, bucket usage, and alert history.
- [ ] Update documentation/README with stabilized procedures.

## Completion Criteria
- [ ] All stages signed off.
- [ ] Checklist archived with run artifacts.
- [ ] File removed from repo after stabilization complete.
