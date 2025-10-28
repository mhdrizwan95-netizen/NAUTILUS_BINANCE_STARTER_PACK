
# Nautilus Dynamic Deck (Instant Control & Monitoring)

## Run the Deck API
```bash
uvicorn ops.deck_api:app --host 0.0.0.0 --port 8002
# open http://localhost:8002
```

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
3. `docker compose up -d hmm_deck` and open `http://localhost:8002`.

A helper list of deletions is in `ops/docker-compose-remove-grafana.txt`.

## Option B – Use override (fallback)
If you prefer not to touch your base file, use `ops/docker-compose.override.yml` (adds the Deck without Grafana removal).

## Dynamic Universe
Use `engine/universe/scorer.py` to compute per-symbol Opportunity Scores every ~30s and feed to strategies + Deck.
