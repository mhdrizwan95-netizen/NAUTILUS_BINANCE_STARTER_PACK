# Roadmap

## Completed ✅

### ML Service Integration (December 2024)
- [x] HMM model training with Gaussian HMM (3-state: BULL/BEAR/CHOP)
- [x] Model versioning and registry (`services/ml_service/app/model_store.py`)
- [x] Hot-reload support via event bus (`model.promoted` events)
- [x] Synthetic data bootstrap when no training data available
- [x] `/train`, `/predict`, `/model` endpoints fully functional

### Param Controller (December 2024)
- [x] LinTS (Linear Thompson Sampling) bandit implementation
- [x] SQLite-backed preset and outcome storage
- [x] Preset registration API (`/preset/register/{strategy}/{instrument}`)
- [x] Parameter selection with contextual features (`/param/{strategy}/{instrument}`)
- [x] Feedback loop for bandit learning (`/learn/outcome/...`)

### Data Ingester (December 2024)
- [x] CCXT-powered OHLCV fetcher for Binance
- [x] Watermark-based incremental ingestion
- [x] Ledger registration for deduplication

### Dynamic Symbol Selection (December 2024)
- [x] `SymbolScanner` wired into `StrategyUniverse.get()`
- [x] Dynamic scoring with return, trend, volatility factors
- [x] Priority: Scanner → `{KIND}_SYMBOLS` → `STRATEGY_SYMBOLS` → `TRADE_SYMBOLS`

### Trade Statistics (December 2024)
- [x] `/trades/stats` endpoint computing win rate, Sharpe, max drawdown
- [x] SQLite query functions for fills and equity curve
- [x] Frontend ops_api integration for real metrics

---

## In Progress 🔄

### Backtest Harness (December 2024 - IMPLEMENTED)
The backtest suite has been implemented with prequential evaluation:

- [x] Market data adapters that stream historical klines/trades (`services/backtest_suite/app/driver.py`)
- [x] Deterministic replay clock that mirrors engine scheduling (`services/backtest_suite/app/clock.py`)
- [x] Fill/fee/slippage model for accurate venue execution simulation (`services/backtest_suite/app/execution.py`)
- [x] Portfolio accounting hooks writing to isolated backtest ledger (`services/backtest_suite/app/metrics.py`)
- [x] CLI/automation surface (`services/backtest_suite/app/cli.py`)
- [x] Sample strategies: momentum breakout, trend follow (`services/backtest_suite/app/strategies.py`)
- [ ] Regression suite testing representative strategies (testing pending)

**Usage:**
```bash
# Build and run
docker compose -f docker-compose.yml -f compose.autotrain.yml -f compose.backtest.yml up -d --build backtest_runner

# Or run locally with historical data
python -m app.cli --strategy momentum --data-dir ./historical --output-dir ./results
```

---

## Planned 📋

### Phase 1: Backtest Infrastructure ✅ COMPLETE
- [x] Implement `services/backtest_suite/app/` with driver, engine, execution modules
- [x] Add historical data replay from CSV files
- [x] Create momentum and trend-follow strategies for testing
- [x] Create parameterized strategy testing framework (grid search) ← `grid_search.py`
- [x] Automated preset generation from results ← `preset_generator.py`
- [ ] Add regression test suite for representative strategies

### Phase 2: Enhanced ML
- [ ] Incremental model updates (partial_fit alternatives for hmmlearn)
- [ ] Multi-asset regime detection (correlated HMM states)
- [ ] Regime transition probability tracking and visualization
- [ ] Ensemble of HMM models with different state counts

### Phase 3: Advanced Governance
- [x] Automated preset generation from backtest results ← `preset_generator.py`
- [ ] Strategy performance-based capital reallocation
- [ ] Multi-horizon parameter optimization (different timeframes)
- [ ] Automatic strategy rotation based on regime

### Phase 4: Production Hardening
- [x] Slack/Telegram notifications for trade events ← `engine/ops/trade_notifier.py`
- [ ] Horizontal scaling (multiple engine instances)
- [ ] Multi-region observability (Prometheus federation)
- [ ] Secrets management (HashiCorp Vault integration)

---

Track progress in the issue tracker or by checking this file.



