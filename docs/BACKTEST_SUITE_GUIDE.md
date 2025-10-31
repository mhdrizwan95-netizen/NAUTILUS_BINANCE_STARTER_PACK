
# Robust Backtest Suite with Embedded Continuous Learning

This suite implements **prequential (test-then-train)** evaluation: at time *t*, the model used to decide is trained only on data up to *t-1*. After the outcome at *t* is observed, the learner may update (on a cadence). That mirrors production **online learning** without leaking the future.

## Why this is the right approach

- **No look-ahead**: decisions never see future labels.
- **Faithful to production**: schedule retrains exactly as your live cron does.
- **Parameter learning**: strategies can adapt via a parameter controller (or embedded bandit).

## Running it

1. Stage research CSVs under `research/<SYMBOL>/<TF>/` with columns at least: `timestamp, open, high, low, close, volume`.
2. Build & run alongside the autotrain services:
   ```bash
   docker compose -f docker-compose.yml -f compose.autotrain.yml -f compose.backtest.yml up -d --build
   docker logs -f backtest_runner
   ```
3. Env knobs (see `.env.example`):
   - `CHUNK_ROWS` – rows per ingest tick when replaying research data.
   - `TRAIN_CRON_MINUTES` – how often to trigger `/train` during simulation (e.g., `360`).
   - `EXACTLY_ONCE` – if `true`, each bar is used at most once across updates.
   - `TRAIN_MIN_POINTS` – minimum observations required to fit a model.
   - `FEE_BP`, `SLIPPAGE_BP` – simple execution friction model.

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
