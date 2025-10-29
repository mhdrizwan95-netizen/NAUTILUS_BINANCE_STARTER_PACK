
# Binance + Nautilus Trader — Adaptive HMM Strategy (Step‑by‑Step)

This is a complete soup‑to‑nuts walkthrough for **training** and **demo/live trading** your HMM→Policy strategy on **Binance** using **Nautilus Trader**.

It assumes macOS or Linux with Python ≥ 3.12 (3.13 supported since Apr 13, 2025; free‑threading off). Use a fresh virtualenv.


## 0) Prerequisites

- Python 3.12 or 3.13 with pip
- `uv` (recommended) or `pip` for installing (`pipx install uv`)
- Git, make, clang toolchain (macOS: `xcode-select --install`)
- Binance account (and **Testnet** keys for Spot or UM‑Futures)
- Optional: Grafana/Prometheus or your own dashboard

References:
- Nautilus installation & supported Python: official docs & releases.
- Binance Testnet (Spot / UM-Futures) docs.


## 1) Create project & environment

```bash
mkdir -p ~/proj/nautilus-hmm && cd $_
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip wheel
```

**Install Nautilus with Binance extras** (stable) or dev wheel:

```bash
# Stable
pip install -U "nautilus_trader[binance]"

# or, development (nightly) wheels:
# pip install -U --pre nautilus_trader --index-url=https://packages.nautechsystems.io/simple
```

Verify import:

```bash
python - <<'PY'
import nautilus_trader as nt
print("Nautilus OK:", nt.__version__)
PY
```


## 2) Project layout (drop-in)

```
nautilus_hmm/
  engine/
    strategies/
      policy_hmm.py
      ensemble_policy.py
  ml_service/
    app.py                # FastAPI: /infer /partial_fit /train
    model_store/
  data/
    raw/                  # downloaded parquet or csv
    processed/
  backtests/
    configs/crypto_spot.yaml
  ops/
    env.example
    runbook.md
  scripts/
    backtest_hmm.py
```

> Keep your **feature schema versioned** (e.g., `FEATURES_V1`). If you change features, bump and retrain.


## 3) Keys & environment

Create `.env` from `ops/env.example` and fill with your keys:

```
# Venue selection
BINANCE_ACCOUNT_TYPE=spot      # or um_futures
BINANCE_IS_TESTNET=true        # false for live

# API
BINANCE_API_KEY=fill_me
BINANCE_API_SECRET=fill_me

# Strategy
SYMBOL=BTCUSDT.BINANCE         # spot
# or: SYMBOL=BTCUSDT-PERP.BINANCE  # perps
```

**Get Testnet keys:**
- Spot Testnet: generate keys and use the testnet base URL.
- UM-Futures Testnet: create Futures Testnet account and keys.


## 4) Data for training

Two options:

**A) Quick-start (trades + book ticker via Binance)**
Use REST to pull trades/aggTrades and book snapshots to craft features. Good enough to train an initial HMM+Policy.

**B) High‑fidelity (recommended) with Tardis**
Pull tick‑level order book deltas + trades and export to Parquet. Use Nautilus’ Tardis integration for backtests and faster model iteration.

Either way, transform to a uniform dataframe with timestamps in **ns**.


## 5) Features (microstructure)

- mid, spread (bp), imbalance ([-1,1]), microprice delta
- realized vol (rolling)
- trade sign imbalance (N‑sec)
- queue dynamics at best levels (Δ size / decay)
- short horizon autocorr (1–2 s)
- volume‑weighted delta
- [perps] time‑to‑funding & recent funding

**Standardize per session** (rolling 60–90 min in crypto).


## 6) Train models

### HMM (state recognizer)
- Choose K=3–5, train on standardized features using multiple inits; pick best log‑likelihood/BIC.
- Persist as `model_store/hmm_v1.pkl`.

### Policy head (state+features → action)
- Train GBDT/MLP on `(state, features)` to predict `(side, qty, limit?)` or a score you threshold.
- Persist as `model_store/policy_v1.pkl`.

### Drift awareness
- Track KL‑divergence of live vs. train feature distributions; if threshold breached, run `/partial_fit` (minibatch EM) and reduce confidence during adaptation.


## 7) Strategy wiring (Nautilus)

- Subscribe to L2 deltas + trades.
- Compute features; POST to `/infer`.
- If `confidence >= min_conf`, apply policy.
- Guardrails before order: `SPREAD | POS | COOLDOWN | LATENCY | DD | KILL`.
- Execution: VWAP anchoring (|microprice − VWAP| > anchor bps), dynamic max spread scaled by realized vol.

Instrument IDs:
- Spot: `BTCUSDT.BINANCE`
- Perps: `ETHUSDT-PERP.BINANCE`, etc.


## 8) Backtest → paper → live

### Backtest
- Load parquet (Binance/Tardis). Initialize `BacktestEngine`. Run the exact strategy and export trades, state timeline, guardrail counts.

### Paper trading
- Wire Binance adapter with `BINANCE_IS_TESTNET=true`.
- Start with qty=0.001 and tight guardrails.
- Log every block reason and feature vector at entry.

### Live (tiny size)
- Flip `BINANCE_IS_TESTNET=false`, **double‑check keys**.
- Keep qty small; scale only after N successful cycles without guardrail hits.


## 9) Ops & monitoring

- Grafana: state histogram, transition heatmap, guardrail counts, latency p95, drift score, funding proximity (perps).
- Daily rollups (Parquet) to S3/MinIO.
- Kill‑switch requires manual re‑enable after any crash.


## 10) Commands cheat‑sheet

```bash
# Install
pip install -U "nautilus_trader[binance]" fastapi uvicorn pandas numpy scikit-learn xgboost hmmlearn duckdb pyarrow python-dotenv httpx

# Start ML service
uvicorn ml_service.app:app --host 0.0.0.0 --port 8010 --workers=1

# Backtest
python scripts/backtest_hmm.py --csv data/BTCUSDT_1m.csv --model engine/models/hmm_policy.pkl --symbol BTCUSDT --quote 100

# Paper trade (Binance testnet)
BINANCE_IS_TESTNET=true TRADING_ENABLED=false uvicorn engine.app:app --host 0.0.0.0 --port 8003 --log-level info

# Live tiny size
BINANCE_IS_TESTNET=false TRADING_ENABLED=true uvicorn engine.app:app --host 0.0.0.0 --port 8003 --log-level info
```

---

## Appendix: Acceptance checks (per symbol‑day)

- No NaNs in features or /infer payloads
- State entropy > ε (non‑degenerate)
- Guardrails never exceeded; reason‑code counts captured
- PnL expectation ≥ 0 after slippage model
- Drift monitor active; partial fit OK
