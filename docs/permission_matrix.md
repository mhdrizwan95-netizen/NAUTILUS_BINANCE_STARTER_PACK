# Command Center Permission Matrix

| Capability | Endpoint(s) | Guard / Dependency | Required Headers | Roles Allowed | Gap |
| --- | --- | --- | --- | --- | --- |
| `read:dashboard` | `GET /api/strategies`, `/api/positions/open`, `/api/metrics/summary`, `/api/backtests/{id}` | none | none | viewer, operator, approver | – |
| `ws:session` | `POST /api/ops/ws-session` | `require_ops_token` | `X-Ops-Token`, optional `X-Ops-Actor` | operator, approver | ✅ actor header not validated |
| `control:config_patch` | `PUT /api/config` | `IdempotentTwoManGuard` | `X-Ops-Token`, `X-Ops-Approver`, `Idempotency-Key`, optional `X-Ops-Actor` | operator + approver | – |
| `control:pause` / `control:resume` | `POST /api/ops/kill-switch` | `IdempotentTwoManGuard` | `X-Ops-Token`, `X-Ops-Approver`, `Idempotency-Key` | operator + approver | – |
| `control:flatten` | `POST /api/ops/flatten` | `IdempotentTwoManGuard` | `X-Ops-Token`, `X-Ops-Approver`, `Idempotency-Key` | operator + approver | – |
| `config:reload` | `POST /api/governance/reload` | `TokenOnlyGuard` | `X-Ops-Token`, optional `Idempotency-Key` | operator, approver | ✅ two-man not enforced |
| `strategy:patch` | `PATCH /api/strategies/{id}` | `require_ops_token` | `X-Ops-Token` | operator, approver | ❌ two-man + idempotency missing |
| `strategy:start` / `strategy:stop` / `strategy:update` | `POST /api/strategies/{id}/start|stop|update` | `IdempotentTwoManGuard` | `X-Ops-Token`, `X-Ops-Approver`, `Idempotency-Key` | operator + approver | – |
| `strategy:universe_refresh` | `POST /api/universe/{id}/refresh` | `require_ops_token` | `X-Ops-Token` | operator, approver | ✅ consider idempotency |
| `orders:cancel` | `POST /api/orders/cancel` | `require_ops_token` | `X-Ops-Token` | operator, approver | ✅ bulk cancel not audited |
| `funds:transfer` | `POST /api/account/transfer` | `require_ops_token` | `X-Ops-Token` | operator, approver | ❌ dual approval + audit missing |
| `events:trade` | `POST /api/events/trade` | `require_ops_token` | `X-Ops-Token` | operator, approver | ✅ payload not sanitized |
| `backtest:start` | `POST /api/backtests` | `IdempotentTwoManGuard` | `X-Ops-Token`, `X-Ops-Approver`, `Idempotency-Key` | operator + approver | – |

Legend: ✅ = needs follow-up hardening, ❌ = critical gap, – = compliant.

