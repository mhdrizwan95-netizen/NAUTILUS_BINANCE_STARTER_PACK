# Command Center Launch Checklist

## Shadow Mode Parity
- [ ] Run `./smoke_shadow.sh` and confirm trading stays disabled (`trading_enabled == false`).
- [ ] Verify WebSocket dashboards mirror production metrics without sending control headers.

## Control API Idempotency
- [ ] Pause, resume, and flatten via Command Center twice in a row; ensure server returns identical `Idempotency-Key` responses.
- [ ] Confirm `POST /api/account/transfer` and `PATCH /api/strategies/{id}` remain on the follow-up list for IdempotentGuard adoption; document the replay-risk waiver if shipping without it.

## Policy Guards & Operator Controls
- [ ] Check `ops/middleware/control_guard.py` reload path for OPS token rotation in single-operator mode.
- [ ] Ensure high-risk routes (`kill-switch`, `flatten`, `config`, `transfer`, `strategy patch`, `governance reload`) are wired to `IdempotentGuard` (or stricter) and emit audit payloads.
- [ ] Validate kill switch UI blocks submission without reason.

## Universe & Selector Gates
- [ ] Review latest `ops/strategy_weights.json` and `ops/strategy_registry.json` for canary limits and promotions.
- [ ] Confirm `universe/service.py` respects quarantine cooldowns and promotion thresholds.

## Rollback & Audit Trail
- [ ] Tail `ops/logs/control_actions.jsonl` to confirm every control change is recorded with actor call-sign and idempotency key.
- [ ] Exercise `docs/OPS_RUNBOOK.md` rollback steps and verify strategy weights revert.

## Observability & Smoke
- [ ] Run `curl -fsS http://localhost:8002/readyz` and `http://localhost:8003/readyz`.
- [ ] Open Grafana dashboards to verify Prometheus scrape targets are green.
- [ ] Execute `python -m ops.quickcheck` (or `make smoke`) to ensure end-to-end readiness.
