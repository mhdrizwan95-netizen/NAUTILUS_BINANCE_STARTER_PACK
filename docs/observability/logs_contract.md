# NAUTILUS Command Center Logging Contract

## Level & Format
- Emit JSON lines (`application/log+json`) with UTC timestamps.
- Fields: `ts`, `service`, `level`, `msg`, `event`, `correlation_id`, `account`, `symbol`, `extra`.
- `correlation_id` carries UUIDv4 from ingress (HTTP `X-Request-ID` or websocket handshake) and is propagated to downstream clients.
- Use `event` for machine-parsable identifiers (e.g. `order.submitted`, `risk.breaker_open`).
- `msg` stays human readable; no secrets or PII.

## Redaction Policy
- Redact secrets/keys via best-effort map (`REDACTION_KEYS = ["api_key","secret","token","signature","passphrase"]`).
- Reject log attempts that include values matching `BINANCE_API_KEY`, `OPS_API_TOKEN`, `GF_SECURITY_ADMIN_PASSWORD` (or file-backed `GF_SECURITY_ADMIN_PASSWORD__FILE` contents), or any configured secret.
- Apply redaction to both structured fields and stringified payloads before logging.

## Correlation Rules
- HTTP: middleware injects `correlation_id` from header or generates new one, adds to response header.
- Async tasks (background loops, strategy broadcasts) must accept a `ctx: LogContext` object exposing `.child(event=...)` for propagation.
- Websocket streams: first message includes `{ "type": "hello", "correlation_id": "…" }`; every push logs with same id.

## Sampling & Levels
- Default level `INFO`. Use `DEBUG` only when `OBS_DEBUG=1`.
- Log sampling for noisy events (`orderbook_update`, `heartbeat`) via token-bucket (max 1/5s) and aggregate counts in metrics.

## Delivery
- Services write to stdout (`StdoutLogger`) so Docker can ship logs.
- `fluent-bit` / Loki Agent tail container output and forward to Loki with labels: `app`, `stage`, `correlation_id`.

## Error Handling
- `ERROR`: include `stack`, `exception.type`, `exception.message`.
- `CRITICAL`: trigger on-call and include `incident_id` referencing alert.
- Never swallow exceptions silently; log and re-raise when appropriate.

## Example
```json
{"ts":"2025-11-01T19:25:04.231Z","service":"ops-api","level":"INFO","event":"order.promoted","correlation_id":"f916dbaf-86fb-42ec-8c14-6a458dbe9276","symbol":"BTCUSDT","account":"binance-spot","msg":"Promoted strategy hmm_v2","extra":{"latency_ms":82}}
```
