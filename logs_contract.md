# Logs & Correlation Contract

Summary
- Every HTTP response from engine and ops includes an `X-Request-ID` header.
- If a client supplies `X-Request-ID`, it is propagated; otherwise a UUIDv4 hex is generated.
- Ops forwards `X-Request-ID` to downstream services (e.g., ML `/health`, `/train`).
- Use this ID to correlate logs and traces across services and dashboards.

Headers
- Incoming: `X-Request-ID` (optional)
- Outgoing: `X-Request-ID` (always present)

Usage
- Clients set a stable ID per logical operation (e.g., UI button → backend → ML).
- Reverse proxies/gateways can inject if missing.
- Log aggregators can index on `X-Request-ID` for end-to-end views.

Future (optional)
- Add OpenTelemetry FastAPI instrumentation and OTLP exporter to enrich traces, using `X-Request-ID` as a span link for compatibility with existing logs.

