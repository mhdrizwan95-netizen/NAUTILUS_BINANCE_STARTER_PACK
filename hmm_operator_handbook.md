# HMM Trading System — Operator Handbook (v1.0)

## 🧭 System Overview

The HMM Trading System is a modular, adaptive trading framework integrating **probabilistic market modeling**, **multi-symbol execution**, **real-time monitoring**, and **automated retraining**.

It evolves through 12 milestones (M0–M12), culminating in a self-observing, multi-asset trading organism.

### System Architecture (M12)

```
                        ┌───────────────────────────┐
                        │     Binance Data Feed     │
                        └────────────┬──────────────┘
                                     │
                                     ▼
                             Feature Extractor
                                     │
                                     ▼
                        ┌───────────────────────────┐
                        │     ML Service (HMM)      │
                        │ /train /infer /promote    │
                        │  Blue/Green model swap    │
                        └────────────┬──────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │ Nautilus Strategy Core  │
                        │  Dynamic sizing, risk   │
                        │  Guardrails & policy    │
                        └────────────┬────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │ Execution (Paper/Live)  │
                        │  BTC & ETH symbols      │
                        └────────────┬────────────┘
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │  Dashboard + Prometheus Metrics  │
                    │  WebSocket updates & Grafana     │
                    └──────────────────────────────────┘
```

### Dataflow Summary

```
Tick data → Feature sequences → HMM / policy → Actions (BUY/SELL/HOLD)
→ Guardrails check → Nautilus fills (slippage model) → Trades → CSV logs →
Prometheus metrics → Dashboard / Grafana
```

## ⚙️ Environment Setup

### macOS or Linux (local)
```bash
cd ~/proj/nautilus-hmm/NAUTILUS_BINANCE_STARTER_PACK
python3 -m venv ../.venv
source ../.venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -U "nautilus_trader[binance]" fastapi uvicorn hmmlearn scikit-learn pandas pyarrow httpx jinja2 prometheus-client pyyaml
export PYTHONPATH=$(pwd)
```

### Optional Docker Compose for Observability
```bash
cd ops
docker compose -f compose.observability.yml up -d
```

### .env Example
```
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret
BINANCE_IS_TESTNET=true
TRADING_ENABLED=true
```

## 🧠 Core Components

### ML Service (`ml_service/app.py`)
Manages Hidden Markov Models (HMM) and policy layers. Supports model versioning with blue/green deployment.

| Endpoint | Description |
|-----------|--------------|
| `/train` | Train model, return tag (v-YYYYMMDDTHHMMSS) |
| `/models` | List loaded tags and active tag |
| `/promote` | Promote a model tag to active |
| `/infer` | Infer market state & action |
| `/load` | Load model tag without promoting |

Run:
```bash
uvicorn ml_service.app:app --host 0.0.0.0 --port 8010
```

Example:
```bash
curl -s -X POST http://127.0.0.1:8010/train -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","feature_sequences":[[[1,2,3],[2,3,4],[3,4,5]]]}'
```

### Backtest Harness (`backtests/run_backtest.py`)
Simulates execution using Parquet tick data.

**Outputs:**
- `trades.csv`: per-trade metrics (vol_bp, spread_bp, l1_depth)
- `guardrails.csv`: blocked trade reasons
- `state_timeline.csv`: inferred states
- `data_quality_issues.csv`: detected feed anomalies

Run:
```bash
python backtests/run_backtest.py --config backtests/configs/crypto_spot.yaml
```

### Strategy Layer (`strategies/hmm_policy/`)
Implements dynamic sizing, per-symbol configuration, and global risk budget.

- **Dynamic sizing:** `qty = k * |exp_edge| / vol_bp`
- **Guardrails:** enforce min confidence, per-state DD limit, daily risk, cooldowns
- **Symbols:** BTCUSDT + ETHUSDT (multi-symbol mode)

### Ops API (`ops/ops_api.py`)
Controls trading lifecycle and retraining triggers.

| Endpoint | Description |
|-----------|--------------|
| `/status` | Current trading flag, ML health |
| `/kill` | Toggle trading_enabled flag |
| `/retrain` | Force model retraining |

Run:
```bash
uvicorn ops.ops_api:APP --host 0.0.0.0 --port 8060
```

### Dashboard (`dashboard/app.py`)
Live telemetry interface: displays PnL, states, guardrails, and confidence via WebSocket + Prometheus metrics.

Run:
```bash
uvicorn dashboard.app:app --host 0.0.0.0 --port 8050
```

Access:
- **Web UI:** http://127.0.0.1:8050
- **Metrics:** http://127.0.0.1:8050/metrics

### Grafana Integration
Import `hmm_trader_grafana_dashboard.json` into Grafana.

Prometheus scrape example:
```yaml
scrape_configs:
  - job_name: hmm-dashboard
    static_configs:
      - targets: ['127.0.0.1:8050']
```

## 🧩 Automation: Canary + Retrain

### Canary Simulation (`ops/canary_sim.py`)
Runs a short backtest for a candidate tag before promotion.

```bash
python ops/canary_sim.py --tag v-YYYYMMDDTHHMMSS --config backtests/configs/crypto_spot.yaml
```

### Nightly Retrain (`ops/nightly_retrain.sh`)
Automated retraining, canary run, and promotion on pass.

Add to cron:
```bash
0 2 * * * cd /Users/mrz/proj/nautilus-hmm/NAUTILUS_BINANCE_STARTER_PACK && bash ops/nightly_retrain.sh >> nightly.log 2>&1
```

### Promotion Flow Diagram
```
          ┌────────────┐
          │ /train new │
          └─────┬──────┘
                │
                ▼
         /load candidate tag
                │
                ▼
        Canary backtest run
                │
       ┌────────┴─────────┐
       ▼                  ▼
  KPI passes?          KPI fails
       │                  │
       ▼                  ▼
 /promote tag        rollback active
```

## 💼 Paper / Live Trading

### Paper Mode
```bash
export BINANCE_IS_TESTNET=true
python ops/run_paper.py --symbol BTCUSDT.BINANCE --symbol ETHUSDT.BINANCE
```

### Live Mode
```bash
export BINANCE_IS_TESTNET=false
python ops/run_live.py --symbol BTCUSDT.BINANCE --symbol ETHUSDT.BINANCE
```

**Risk Controls:**
- Global day risk: $100
- Per-state DD cap: $20
- Min notional: $10
- Global flip cooldown: 1.5s

### Symbol Config Example
```yaml
symbols:
  BTCUSDT.BINANCE:
    min_notional_usd: 10
    base_qty: 0.001
  ETHUSDT.BINANCE:
    min_notional_usd: 10
    base_qty: 0.01
```

## 📊 Monitoring Metrics

| Metric | Description |
|--------|-------------|
| `pnl_realized` | Realized profit/loss (USD) |
| `pnl_unrealized` | Mark-to-market PnL |
| `drift_score` | KLD drift from training distribution |
| `guardrail_trigger_total` | Count per guardrail reason |
| `state_active{id}` | Active state indicator |

**Grafana Alerts:**
- `drift_score > 0.5` for 5m → Model drift warning
- `sum(rate(guardrail_trigger_total[5m])) > 30` → Execution instability
- `abs(pnl_realized) > 100` → Budget exhaustion

## 📊 Monitoring Tools

M15 Calibration Notebook — validates RewardBook convergence and TinyMLP learning safety.

## 🔁 Daily Operator Routine

| Time | Task | Command |
|------|------|----------|
| 08:00 | Verify ML service | `curl http://127.0.0.1:8010/health` |
| 09:00 | Run backtest | `python backtests/run_backtest.py` |
| 12:00 | Check dashboard | http://127.0.0.1:8050 |
| 14:00 | Canary + retrain | `bash ops/nightly_retrain.sh` |
| 17:00 | Paper/live run | `python ops/run_live.py` |
| 20:00 | Check Grafana metrics | `pnl_realized`, `guardrail_trigger_total` |

## 🧰 Troubleshooting Matrix

| Symptom | Likely Cause | Fix |
|----------|--------------|-----|
| ModuleNotFoundError | venv inactive | `source ../.venv/bin/activate` |
| No trades | Guardrails blocking | Lower `min_conf`, adjust `day_usd` budget |
| Dashboard blank | No CSVs in `data/processed` | Run backtest or paper mode |
| /train errors | Missing numpy/pandas | Reinstall deps |
| Grafana no data | Prometheus not scraping | Check `/metrics` endpoint |
| Canary failed | KPI mismatch | Inspect `data/processed/canary_*.log` |
| Trades too small | min_notional too high | Adjust in config |

## 🧮 Maintenance & Versioning

- **Model store cleanup:**
```bash
find model_store -type f -mtime +14 -delete
```

- **Archive rollups:**
```bash
tar czf archives/rollups_$(date +%Y%m%d).tar.gz data/processed/rollups.csv
```

- **Check active tag:**
```bash
cat model_store/active_tag.txt
```

- **Rollback:**
```bash
curl -X POST http://127.0.0.1:8010/promote -H "Content-Type: application/json" -d '{"tag":"v-previous"}'
```

## 🧱 Deployment Flow

### Local (Mac)
1. Activate venv
2. Generate synthetic Parquet
3. Run quickcheck
4. View dashboard

### Server (Linux)
1. Configure `.env` with keys
2. Enable systemd services:
   ```bash
   systemctl enable hmm_ml.service hmm_dash.service
   ```
3. Add cron jobs for nightly retrain
4. Monitor Grafana alerts
5. Review logs under `/var/log/hmm/`

## 🔍 Quickcheck Script

To validate full stack:
```bash
./ops/quickcheck.sh
```
Expected output:
- ✅ ML service healthy
- ✅ Backtest produces CSVs
- ✅ Dashboard `/metrics` accessible
- ✅ Ops API responds
- ✅ Canary + promote cycle successful

## 🧩 Next Phases (Future M13–M15)

| Milestone | Focus |
|------------|--------|
| M13 | Hierarchical HMM (macro/micro regime) |
| M14 | Cross-symbol covariance risk control |
| M15 | Reinforcement fine-tuning on live feedback |

---

**End of Handbook** — This file can be committed as `HMM_OPERATOR_HANDBOOK.md` in repo root or `/docs/` folder for operational reference.
