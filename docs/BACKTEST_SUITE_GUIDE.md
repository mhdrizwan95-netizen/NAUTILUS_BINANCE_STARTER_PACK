
# Robust Backtest Suite with Embedded Continuous Learning

> [!TIP]
> **Implementation Status: COMPLETE (December 2024)**  
> The backtest suite is now fully implemented with prequential evaluation.

This suite implements **prequential (test-then-train)** evaluation: at time *t*, the model used to decide is trained only on data up to *t-1*. After the outcome at *t* is observed, the learner may update (on a cadence). That mirrors production **online learning** without leaking the future.

## Quick start

1. Drop historical bars into `historical/` with columns at minimum<br>`timestamp (ms), open, high, low, close, volume`.
2. Launch the suite (it expects `ml_service` and `param_controller` to be up):

   ```bash
   docker compose -f docker-compose.yml -f compose.autotrain.yml up -d ml_service param_controller
   docker compose -f compose.backtest.yml up -d --build
   docker logs -f backtester
   ```

3. Or run directly with the CLI:
   ```bash
   cd services/backtest_suite
   python -m app.cli --strategy momentum --data-dir /path/to/historical --output-dir ./results
   ```

4. Adjust behaviour via environment variables:
   - `RETRAIN_EVERY_MIN` — cadence for embedded HMM retrains (e.g. `360`).
   - `STEP_MINUTES` — bar granularity.
   - `EXACTLY_ONCE` — toggle strict one-pass training.
   - `COST_BPS`, `SLIPPAGE_BPS_PER_VOL` — simple cost model.

Stop the container when the simulation finishes; it writes metrics to `/results/`.

## What's included

| Module | Purpose |
|--------|---------|
| `app/cli.py` | Command-line entry point with argument parsing |
| `app/engine.py` | Main prequential evaluation loop |
| `app/driver.py` | Data loading from CSV files |
| `app/clock.py` | Deterministic simulation clock |
| `app/execution.py` | Fill/fee/slippage execution model |
| `app/metrics.py` | Performance metrics calculation |
| `app/strategies.py` | Sample strategies (MomentumStrategy, TrendFollowStrategy) |
| `app/config.py` | Configuration settings |

## Why this is the right approach

- **No look-ahead**: decisions never see future labels.
- **Faithful to production**: schedule retrains exactly as your live cron does.
- **Parameter learning**: strategies can adapt via a parameter controller (or embedded bandit).

## Running it

1. Put a CSV at `historical/sample.csv` with columns at least: `timestamp(ms), open, high, low, close, volume`.
2. Build & run:
   ```bash
   docker compose -f compose.backtest.yml up -d --build
   docker logs -f backtester
   ```
3. Env knobs:
   - `RETRAIN_EVERY_MIN` – how often the embedded HMM retrains (e.g., `360`).
   - `STEP_MINUTES` – bar granularity.
   - `EXACTLY_ONCE` – if `true`, each bar is used at most once across updates.
   - `COST_BPS`, `SLIPPAGE_BPS_PER_VOL` – simple cost model.
   - `LEDGER_DB` and `DATA_INCOMING` default to `/research/manifest.sqlite` and `/research/incoming`; keep these paths when running in CI or staging so research jobs never touch the production `/ml` mount.
   - The trainer mirrors production behaviour: ledger files are claimed atomically and requeued if the job fails, so you never “burn” research data during a crash loop.
   - `research_scrubber` (new optional service) runs the cron defined in `ops/research_purge.cron` to delete `/research/*` directories older than 30 days; adjust the cron if compliance requires longer retention.

## Extending to your stack

- Replace the embedded `HMMModel` with **real** `ml_service` calls:
  - At each step, the strategy calls `ml_service /predict` for features/regime probs.
  - Retraining is scheduled externally (or call `/train` in sim when cadence ticks).
- Replace stub strategies with your engine; wire the **param_controller**:
  - `GET /param/{strategy}/{instrument}?features[...]`
  - `POST /learn/outcome/{strategy}/{instrument}/{preset_id}` only **after** the trade completes.
- For hyperparameter selection, wrap the sim in **purged, rolling-origin CV** with an **embargo** (López de Prado) to avoid leakage from overlapping labels.

## Does this “fill the backtest gap”?

It **closes the *forward-simulation* gap** (how the system behaves while learning). You still want a curated, multi‑year **research dataset** and a suite of **walk‑forward** tests with transaction-cost modeling to select strategies and presets. Use this sim to validate **adaptivity mechanics**; use the research suite to decide **what to adapt**.

## Guardrails in simulation

- **Test then train** only (prequential). Never update before you record the outcome.
- **Embargo overlapping outcomes** when outcomes span horizons > 1 bar.
- **Freeze parameters mid‑trade**; apply new params to **new** positions only.
- Enforce **maximum daily param changes** and **hysteresis** thresholds.
