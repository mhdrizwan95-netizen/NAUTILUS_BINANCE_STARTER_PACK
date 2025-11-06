# Command Center Permission Matrix

| Capability | Endpoint(s) | Guard / Dependency | Required Headers | Roles Allowed | Gap |
| --- | --- | --- | --- | --- | --- |
| `read:dashboard` | `GET /api/strategies`, `/api/positions/open`, `/api/metrics/summary`, `/api/backtests/{id}` | none | none | viewer, operator | – |
| `ws:session` | `POST /api/ops/ws-session` | `require_ops_token` | `X-Ops-Token`, optional `X-Ops-Actor` | operator | ✅ actor header not validated |
| `control:config_patch` | `PUT /api/config` | `IdempotentGuard` | `X-Ops-Token`, `Idempotency-Key`, optional `X-Ops-Actor` | operator | – |
| `control:pause` / `control:resume` | `POST /api/ops/kill-switch` | `IdempotentGuard` | `X-Ops-Token`, `Idempotency-Key` | operator | – |
| `control:flatten` | `POST /api/ops/flatten` | `IdempotentGuard` | `X-Ops-Token`, `Idempotency-Key` | operator | – |
| `config:reload` | `POST /api/governance/reload` | `TokenOnlyGuard` | `X-Ops-Token`, optional `Idempotency-Key` | operator | ✅ consider adding actor context |
| `strategy:patch` | `PATCH /api/strategies/{id}` | `require_ops_token` | `X-Ops-Token` | operator | ✅ add idempotency + audit payload |
| `strategy:start` / `strategy:stop` / `strategy:update` | `POST /api/strategies/{id}/start|stop|update` | `IdempotentGuard` | `X-Ops-Token`, `Idempotency-Key` | operator | – |
| `strategy:universe_refresh` | `POST /api/universe/{id}/refresh` | `require_ops_token` | `X-Ops-Token` | operator | ✅ consider idempotency |
| `orders:cancel` | `POST /api/orders/cancel` | `require_ops_token` | `X-Ops-Token` | operator | ✅ bulk cancel not audited |
| `funds:transfer` | `POST /api/account/transfer` | `require_ops_token` | `X-Ops-Token` | operator | ✅ add audit context |
| `events:trade` | `POST /api/events/trade` | `require_ops_token` | `X-Ops-Token` | operator | ✅ payload not sanitized |
| `backtest:start` | `POST /api/backtests` | `IdempotentGuard` | `X-Ops-Token`, `Idempotency-Key` | operator | – |

Legend: ✅ = needs follow-up hardening, ❌ = critical gap, – = compliant.
