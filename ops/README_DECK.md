
# Nautilus Dynamic Deck (Instant Control & Monitoring)

## Run the Deck API
```bash
uvicorn ops.deck_api:app --host 0.0.0.0 --port 8002
# open http://localhost:8012 if using docker-compose defaults
```

Set `DECK_STATIC_DIR` if you want to serve the UI from an alternate path. When running under docker-compose, you can override the ops dependency via `.env` (see `ops/compose_env_example/.env.example`).

## REST / WS surface
- `POST /risk/mode` — set trading mode (`red|yellow|green`)
- `POST /kill` — toggle killswitch (`{"enabled": true}`)
- `POST /allocator/weights` — update risk share for a strategy
- `POST /strategies/{name}` — toggle `enabled` flag and/or risk share
- `POST /metrics` — backwards-compatible metrics update (partial fields)
- `POST /metrics/push` — push live metrics + `pnl_by_strategy` for the allocator/Deck badges
- `POST /trades` — optional trade/fill ingest (updates latency p50/p95)
- `POST /top` — push Opportunity Score leaderboard
- `GET /status` / `WS /ws` — streaming snapshot for the Deck UI

## Security (optional): Deck Token

POST routes can be guarded with a shared token. Set the token on the Deck container:

```bash
DECK_TOKEN=change-me
```

Clients (engine allocator / metrics) must send: `X-Deck-Token: <token>`.

Behavior:
- `DECK_TOKEN` unset or empty → token auth disabled (open POSTs).
- `DECK_TOKEN` set → all POSTs require the header; GET/WS remain open.

## Manual Binance Transfers (Universal)

The Deck can initiate Binance universal transfers for Funding ⇄ Spot ⇄ USDⓈ-M (and optional Margin/COIN-M legs).

1. Provide SAPI credentials on the Deck container:
   - `BINANCE_API_KEY`
   - `BINANCE_API_SECRET`
   - Optional `BINANCE_SAPI_BASE` (defaults to `https://api.binance.com`)
2. Control which wallets are exposed via `DECK_TRANSFER_ALLOW` (comma separated). Default: `FUNDING,MAIN,UMFUTURE`. Add `MARGIN`, `ISOLATEDMARGIN`, `CMFUTURE` only if you intend to use them.
3. The UI renders a **Transfers (Manual)** panel with quick buttons and a recent activity log.
4. API surface:
   - `GET /transfer/types` → returns currently allowed wallet pairs.
   - `POST /transfer` (token‑guarded) with body:
     ```json
     {
       "from_wallet": "FUNDING",
       "to_wallet": "UMFUTURE",
       "asset": "USDT",
       "amount": 25,
       "symbol": "BTCUSDT" // only required for isolated margin flows
     }
     ```
   Successful calls broadcast on the WebSocket and appear in the UI log (last 20 transfers).

## Optional Allocator Service (off by default)

We ship an allocator daemon that tilts strategy `risk_share` by rolling PnL. Enable it on demand with Compose profiles:

```bash
docker compose --profile allocator up -d hmm_allocator
```

Disable by stopping the service or omitting the profile. Environment knobs:
`ALLOCATOR_REFRESH_SEC`, `ALLOCATOR_EMA_ALPHA`, `ALLOCATOR_EXPLORATION`,
`ALLOCATOR_MIN_SHARE`, `ALLOCATOR_MAX_SHARE`.

Allocator targets the Deck at `DECK_URL` (e.g., `http://hmm_deck:8002`). If Deck token auth is enabled, set the same `DECK_TOKEN` for the allocator container.

## Wire dynamic policy into RiskRails
Import from `engine.dynamic_policy` and replace static env caps with the helper functions.

```python
from engine.dynamic_policy import (
    MarketSnapshot, AccountState, StrategyContext,
    choose_mode, dynamic_position_notional_usd,
    dynamic_concurrent_limits, dynamic_drawdown_limits,
)
```

## Option A – Update docker-compose.yml directly (recommended)
1. Remove Grafana (and Loki/Promtail if present) service blocks from `docker-compose.yml`.
2. Append the contents of `ops/docker-compose-add-deck.snippet.yml` under `services:`.
3. `docker compose up -d hmm_deck` and open `http://localhost:${DECK_PORT:-8012}`.

A helper list of deletions is in `ops/docker-compose-remove-grafana.txt`.

## Option B – Use override (fallback)
If you prefer not to touch your base file, use `ops/docker-compose.override.yml` (adds the Deck without Grafana removal).

## Dynamic Universe
Use `engine/universe/scorer.py` to compute per-symbol Opportunity Scores every ~30s and feed to strategies + Deck.

## Token Auth (optional)
Set `DECK_TOKEN` on the Deck container to require `X-Deck-Token` on all POST routes.
- If `DECK_TOKEN` is unset/empty → POSTs are open (default).
- If set → POSTs require the header; GET `/status` and `WS /ws` stay open.

## Optional Allocator Service
An allocator daemon can auto-tilt strategy `risk_share` based on rolling PnL.
It's disabled by default via Compose profiles.

Start (with Deck running):
```bash
docker compose --profile allocator up -d hmm_allocator
```

Env knobs: `ALLOCATOR_REFRESH_SEC`, `ALLOCATOR_EMA_ALPHA`, `ALLOCATOR_EXPLORATION`,
`ALLOCATOR_MIN_SHARE`, `ALLOCATOR_MAX_SHARE`. It posts to `DECK_URL` and, if auth is on,
sends `X-Deck-Token`.
