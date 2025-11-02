# Developer Guide

This guide explains how to bootstrap a development environment, run services locally, execute the test suite, and extend the Nautilus HMM stack safely.

## Environment

| Requirement | Notes |
|-------------|-------|
| Python 3.10+ | The repo targets Python 3.10; create a virtualenv for tooling and unit tests. |
| Docker & Docker Compose | Required for the full stack (`docker compose` v2 syntax). |
| make | `Makefile` wraps common workflows; install GNU Make on macOS via Homebrew if needed. |
| Optional: `ib_insync` | Needed only when developing the IBKR connector (`pip install ib-insync`). |

Install Python dependencies inside a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Bootstrapping the stack

1. Copy the environment template and tweak credentials/risk knobs.
   ```bash
   cp env.example .env
   ```
2. Ensure the shared Docker network exists (compose expects it).
   ```bash
   docker network create nautilus_trading_network || true
   ```
3. Build and launch services with the Makefile helpers.
   ```bash
   make build          # build images
   make up-core        # start engines, ops, universe, situations, screener
   make up-obs         # optional: Prometheus + Grafana bundle
   ```
4. Verify metrics and health.
   ```bash
   make smoke-exporter
   curl http://localhost:8003/readyz | jq
   curl http://localhost:8002/status | jq
   ```
5. Stop services when done.
   ```bash
 make down           # core stack
 make down-all       # core + observability bundle
 ```

> Runtime images now ship with `tini` + `uvicorn` baked in, so `docker run nautilus_binance_starter_pack-engine_binance` works out-of-the-box. Compose can still override the command when necessary.

### Running components directly

- Engine API (hot reload):
  ```bash
  uvicorn engine.app:app --reload --port 8003
  ```
- Ops API:
  ```bash
  uvicorn ops.ops_api:APP --reload --port 8002
  ```
- ML service (not part of docker-compose by default):
  ```bash
  uvicorn ml_service.app:app --host 0.0.0.0 --port 8010 --reload
  ```

Set `PYTHONPATH=.` when running modules directly so relative imports resolve.

## Repository layout hints

| Path | Highlights |
|------|------------|
| `engine/` | FastAPI app, order router, risk rails, metrics, storage, state management. |
| `engine/core/` | Venue adapters, portfolio accounting, reconciliation daemon, event bus, strategy scheduler. |
| `engine/strategies/` | Unified strategy implementations (HMM policy, ensemble fusion, trend, scalping, momentum, listing sniper, meme sentiment, airdrop promo, symbol scanner). |
| `ml_service/` | Model training/inference API, hierarchical HMM implementation, model store. |
| `ops/` | Ops API, capital allocator, governance daemons, executor, observability plumbing. |
| `ops/observability/` | Prometheus/Grafana configs, alerting rules, validation scripts. |
| `universe/`, `situations/`, `screener/` | Supporting FastAPI microservices for symbol selection and pattern detection. |
| `engine/storage/` | SQLite facade and schema for orders, fills, positions, and equity snapshots. |
| `engine/logs/`, `engine/state/`, `data/runtime/` | JSONL logs, portfolio snapshots, SQLite database. |
| `scripts/`, `pipeline/`, `notebooks/` | Research pipelines, backtests, model registry helpers, exploratory notebooks. |
| `tests/` | Pytest suite covering engine, strategy, ops, and ML behaviour. |

## Tests

Run the full suite:

```bash
pytest
```

Common subsets:

```bash
pytest tests/test_strategy.py -k buy
pytest tests/test_ops_aggregate.py -vv
pytest tests -k "kraken or binance"
```

Tips:

- Tests mock HTTP calls with `respx`. When adding client code, expose request factories so they can be patched.
- Use `pytest.mark.asyncio` for coroutine tests.
- Keep fixtures deterministic—seed RNGs and avoid wall-clock dependence.
- SQLite-backed tests run against in-memory DBs; keep schema changes backward compatible.
- If you add a new venue adapter, extend `tests/test_order_router.py` and build fixture payloads that match the venue API.

## Coding conventions

- Prefer async I/O (`httpx.AsyncClient`, `asyncio`) inside request handlers; the only blocking threads should be strategy background loops.
- Always surface configuration via environment variables or dataclasses—never hard-code credentials or sensitive paths.
- For file writes, use atomic patterns (`Path.write_text` to temp file + `Path.replace`) as seen in `engine/state.py`.
- Instrument new behaviours with Prometheus metrics or logs; register metrics in `engine/metrics.py` or `ops/prometheus.py`.
- Route errors through FastAPI HTTP exceptions with informative `detail` payloads; log context but avoid leaking secrets.
- When touching `engine/strategy.py`, ensure `RiskRails.check_order` remains in the path and `Cache` idempotency semantics are preserved.
- Follow existing logging style: structured messages with component prefixes (`logger.info("[COMPONENT] ...")`).
- Keep docstrings and comments concise; add explanatory comments only when intent is non-obvious.

## Observability during development

- `make smoke-exporter` validates accounting invariants (`equity_usd = cash_usd + market_value_usd`).
- `make smoke-prom` lists active Prometheus targets; useful when wiring new exporters.
- `ops/observability/validate_obs.sh` runs saved PromQL checks to confirm dashboards stay green after changes.
- New metrics should include labels compatible with existing dashboards (`venue`, `symbol`, `model`, `role`).

## State & data considerations

- Portfolio state persists under `engine/state/portfolio.json`; respect atomic writes when modifying schema.
- Orders/fills go to both JSONL logs and `data/runtime/trades.db`; if you change schemas, update `engine/storage/schema.sql` and migration code.
- Idempotency cache lives at `engine/state/idempotency_cache.json`; flush it via `engine/idempotency.py` when changing key formats.
- When developing universe/screener logic, watch rate-limit gauges (`RATE_LIMIT_429`) and respect Binance testnet quotas.
- Production ML ingestion now mounts `/ml` (`LEDGER_DB=/ml/manifest.sqlite`, `DATA_DIR=/ml/data`) to isolate retrains from research workloads.
- Research and backtest pipelines mount the `/research` volume. Set `LEDGER_DB=/research/manifest.sqlite` and `DATA_INCOMING=/research/incoming` (see `compose.backtest.yml`) so CI/staging jobs do not write into the production `/ml` mount.
- Deterministic retrains are controlled by `TRAIN_SEED`; override it per run to reproduce models. The ML service now records `train_seed` in model metadata so audit trails capture the exact RNG state used during promotion.

## Submitting changes

- Run `pytest` before opening a PR; add tests for new behaviour or regressions.
- Update documentation (`README.md`, `docs/*`) when you add a venue, change APIs, or modify operational procedures.
- Mention relevant Makefile targets or configuration knobs in commit messages to help operators.
- Provide roll-back instructions or release notes if changes require coordinated deploys.

Happy hacking! Keep the docs current—the quickest way to land smoother changes is to ensure future you (or the next teammate) can find the context right here.
