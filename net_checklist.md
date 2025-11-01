Network Wiring Checklist

- Timeouts
  - Engine venue clients: httpx timeouts from env (`BINANCE_API_TIMEOUT` seconds). Backoff on 418/429 implemented.
  - Ops/ML/Ingester endpoints: set short, explicit timeouts; avoid relying on defaults.
  - Frontend fetches: Abort after 10s via shared timeout helper to avoid hung UI.

- Retries & Backoff
  - Engine REST: retries with exponential backoff on throttle (418/429).
  - Ops ML calls: add 2–3 attempts with small backoff (see `ops/ops_api.py`).
  - DEX oracle: 3 attempts with backoff (see `engine/dex/oracle.py`).

- Connection Pooling
  - Use shared `httpx.AsyncClient` with `Limits(max_connections=10, max_keepalive_connections=10)` in background loops (pnl/exposure/aggregate, dashboard).

- DNS & Proxies
  - Enable `trust_env=True` for clients used to call internal/external HTTP to respect `HTTP(S)_PROXY` and system certs when present.

- TLS
  - Default `verify=True` on httpx; no custom cert paths required. Use system CA bundle in slim images via `ca-certificates`.

- Keep-Alive
  - Prefer long-lived AsyncClients in loops; avoid recreate-per-request in hot paths to reduce handshake overhead.
  - Executor heartbeat uses pooled httpx client (`Limits(8/4)`) and respects proxies via `trust_env=True`.

- Circuit Breakers
  - Executor breaker implemented in ops/main.py. For HTTP surfaces, keep short timeouts and soft retries to bound waiting.
