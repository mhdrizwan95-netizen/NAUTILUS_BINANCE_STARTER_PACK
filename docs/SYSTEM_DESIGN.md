# System Design

## 🧩 Architecture Overview

OPS (control plane)
├── Strategy Router      → sends trade intents by model weight
├── Capital Allocator    → adjusts model budgets
├── Governance Daemon    → enforces policies & reacts to alerts
├── Canary Manager       → evaluates and promotes models
├── PnL Dashboard        → live metrics & daily exports
└── Event Bus (SSE/Redis)↔ broadcasts all system events

Engine (execution plane)
├── Order Router + Risk Rails
├── OMS (OCO, trailing, cancel/replace)
├── Persistence + Recovery
├── Metrics + Prometheus exporter
└── Idempotent API endpoints

## 🔄 Data Flow

```bash
              ┌────────────────────────────────────────────────────┐
              │                   STRATEGY EVENT                   │
              │  e.g. {"symbol":"BTCUSDT.BINANCE","side":"BUY"}    │
              └────────────────────────────────────────────────────┘
                                │
                                ▼
                      ┌──────────────────────┐
                      │ OPS: Strategy Router │
                      └──────────────────────┘
                                │
                      (selects model by weight)
                                │
                                ▼
                  ┌────────────────────────────────┐
                  │ OPS: Capital Allocator          │
                  │ - reads quotas                  │
                  │ - scales trade size by budget   │
                  └────────────────────────────────┘
                                │
                                ▼
                  ┌────────────────────────────────┐
                  │ ENGINE API (/orders)            │
                  │ - validates via Risk Rails      │
                  │ - submits to exchange           │
                  │ - logs order JSONL              │
                  └────────────────────────────────┘
                                │
                     (fills, rejections, metrics)
                                │
                                ▼
                  ┌────────────────────────────────┐
                  │ PROMETHEUS / METRICS EXPORTER  │
                  └────────────────────────────────┘
                                │
                      (scraped by OPS)
                                │
                                ▼
             ┌────────────────────────────────────────┐
             │ OPS: PnL Dashboard & Canary Evaluator   │
             │ - merges metrics per model/venue        │
             │ - calculates Sharpe, Drawdown, Winrate  │
             │ - updates strategy_registry.json        │
             └────────────────────────────────────────┘
                                │
                      (event published via BUS)
                                │
                                ▼
             ┌────────────────────────────────────────┐
             │ GOVERNANCE DAEMON                      │
             │ - applies YAML policies                │
             │ - may pause trading, reduce exposure   │
             │ - may promote models                   │
             └────────────────────────────────────────┘
                                │
                      (actions → ENV or files)
                                │
                                ▼
             ┌────────────────────────────────────────┐
             │ CAPITAL ALLOCATOR                      │
             │ - adjusts per-model quotas             │
             │ - writes capital_allocations.json      │
             └────────────────────────────────────────┘
                                │
                      (feedback to Router)
                                │
                                ▼
              ┌──────────────────────────────────────────┐
              │   Next Trading Cycle (self-adaptive)      │
              └──────────────────────────────────────────┘
```

1. **Signal** → `/strategy/signal` (OPS)
   Weighted router picks a model, applies quota, forwards to engine.
2. **Engine Execution**
   Performs risk checks → places order → logs → emits event.
3. **Metrics Aggregation**
   Prometheus scrapes engines; OPS `/dash/pnl` merges per-model.
4. **Governance Loop**
   Subscribes to event bus; enforces YAML policies automatically.
5. **Allocator Loop**
   Periodically reads Sharpe/PnL → recalculates model budgets.
6. **Dashboards / Alerts**
   SSE pushes events to web UI and Telegram in real time.

## 📈 Prometheus Metrics

| Metric | Labels | Meaning |
|---------|---------|---------|
| `orders_submitted_total` | `venue,model` | Submitted count |
| `orders_filled_total` | `venue,model` | Filled count |
| `pnl_realized_total` | `venue,model` | Realized PnL |
| `equity_usd` | `venue` | Current account equity |
| `fill_latency_ms_bucket` | `venue` | Order latency histogram |

## 🧠 Intelligence Stack

| Layer | Responsibility |
|-------|----------------|
| Strategy Selector | Chooses model mix |
| Canary Manager | Measures performance & promotes |
| Governance | Enforces policies & triggers actions |
| Capital Allocator | Adjusts capital dynamically |

## 🔄 Model Lifecycle

```
Backtest → Registry → Canary 10% → Evaluation → Promotion → Capital Growth → Production
     ↓         ↓         ↓          ↓          ↓          ↓            ↓
Validation → Stats → Live Data → Sharpe/PnL → 100% Weight → Auto-budget → Full Trading
```

## 🏗️ Component Details

### Strategy Router
- **Input:** Trading signal payload (`symbol`, `side`, `quote` | `quantity`)
- **Logic:** Probabilistic model selection by weight + capital allocation enforcement
- **Output:** Enriched signal to engine with model tag and quota limits
- **Integration:** Updates PnL metrics, emits routing events

### Capital Allocator
- **Input:** Live equity + model performance metrics
- **Logic:** Sharpe-based reallocation every 30s with cooldowns
- **Output:** Updated `capital_allocations.json` with new quotas
- **Safety:** Hard min/max bounds, market volatility detection

### Canary Manager
- **Input:** Historical performance from registry + live PnL
- **Logic:** Statistical promotion criteria (Sharpe thresholds, trade counts)
- **Output:** Weight updates + governance events
- **Integration:** Triggers capital policy updates on promotion

### PnL Dashboard
- **Input:** Raw Prometheus metrics from all venues/engines
- **Logic:** Model-level aggregation with attribution calculations
- **Output:** Real-time dashboard + CSV exports
- **Integration:** Auto-refreshes every 5 seconds via SSE

## 📊 Configuration Hierarchy

```
Global Defaults (Code)
    ↓
OPS Policies (ops/policies.yaml)
    ↓
Capital Policy (ops/capital_policy.json)
    ↓
Strategy Weights (ops/strategy_weights.json)
    ↓
Live Allocations (ops/capital_allocations.json)
```

## 🔒 Security Model

- **API Authentication:** Bearer tokens via `X-OPS-TOKEN` header
- **Venue Isolation:** Each exchange adapter is separately sandboxed
- **Encrypted Secrets:** API keys via environment variables only
- **Audit Trail:** All decisions logged to immutable JSONL files
- **Rate Limiting:** Applied at both OPS and engine layers

## 🔄 Recovery Architecture

- **State Persistence:** All critical state saved atomically
- **Order Reconciliation:** Startup reconciliation with exchange state
- **Fallback Mode:** Registry-based metrics when live feeds unavailable
- **Circuit Breakers:** Automatic pauses on excessive errors or drawdowns

## 📈 Scaling Considerations

- **Horizontal Engines:** Add Binance/IBKR instances for increased throughput
- **Multi-OPS:** Distributed control planes for high-frequency strategies
- **Metrics Aggregation:** Prometheus federation for multi-region setups
- **Database Sharding:** Partition historical data by time/model

## 🎯 Performance Characteristics

- **Signal Latency:** < 100ms end-to-end (OPS routing + engine execution)
- **Metrics Refresh:** 30s capital allocation, 5s dashboard updates
- **Concurrent Signals:** 100+ signals/second via async processing
- **Storage Efficiency:** Compressed JSONL logs, retention policies
