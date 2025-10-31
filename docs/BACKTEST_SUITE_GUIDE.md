
# Robust Backtest Suite with Embedded Continuous Learning

This suite implements **prequential (test-then-train)** evaluation: at time *t*, the model used to decide is trained only on data up to *t-1*. After the outcome at *t* is observed, the learner may update (on a cadence). That mirrors production **online learning** without leaking the future.

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

