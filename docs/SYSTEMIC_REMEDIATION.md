# Systemic Remediation Log (Phases 7 & 8)

This document records the resolution of critical systemic issues identified and fixed during the Forensic Audit (December 2025).

## 1. Binance Client Optimization (Performance)
*   **Problem**: The application was creating a new `httpx.AsyncClient` for every single API request. This caused a full TCP/SSL handshake for every call, adding ~50-100ms latency per request and increasing connection churn.
*   **Fix**: Refactored `BinanceREST` (`engine/core/binance.py`) to initialize a persistent `self._client` (httpx.AsyncClient) in `__init__` and reuse it for all 20+ API methods.
*   **Outcome**: Significant reduction in API latency and connection overhead.

## 2. Event Bus Optimization (Latency)
*   **Problem**: "Head-of-Line Blocking". The `EventBus` processed events serially, awaiting each handler before moving to the next. A single slow strategy could delay the entire system tick.
*   **Fix**: Updated `EventBus._process_events` (`engine/core/event_bus.py`) to use `asyncio.create_task` for parallel dispatch. Added a `Semaphore(100)` to provide backpressure and prevent OOM during bursts.
*   **Outcome**: Non-blocking event loop; improved system responsiveness and tick handling.

## 3. Ops Authentication (Security)
*   **Problem**: The `require_ops_token` function was hardcoded to bypass validation, leaving the Ops API unprotected.
*   **Fix**: Restored the token validation logic in `engine/ops_auth.py`.
*   **Dev Mode**: Added support for `GLASS_COCKPIT=1` environment variable. If set, the bypass is active (with a warning log) to facilitate local development without token headers.
*   **Outcome**: Secure by default, flexible for developers.

## 4. System Telemetry (Observability)
*   **Problem**: The Frontend dashboard showed "System Status: Unknown" because the Backend never emitted the expected `venue.health` event logic.
*   **Fix**: Implemented `_start_venue_monitor` in `engine/app.py` to periodically check `BinanceMarketStream` connectivity and broadcast `venue.health` status to the WebSocket.
*   **Outcome**: Accurate system health reporting in the UI.

## 5. Other Fixes
*   **Risk Engine**: Enforced `RiskRails` checks on all programmatic orders.
*   **Float Precision**: Switched remaining critical paths to `Decimal` or safe rounding.
*   **Redis Security**: Added password support for River ML persistence.

---
*Last Updated: 2025-12-13*
