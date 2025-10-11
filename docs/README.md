# 🧠 Nautilus HMM – Autonomous Multi-Venue Trading System

This repository hosts an **autonomous trading stack** integrating Binance, IBKR, and adaptive AI strategies under one coordinated control layer.

### 🚀 Capabilities

| Layer | Description |
|-------|--------------|
| **Engine Layer** | FastAPI micro-engines (Binance, IBKR) with risk rails, idempotency, persistence |
| **OPS Layer** | Aggregates venues, handles routing, governance, and dashboards |
| **Risk & Compliance** | Configurable rails: min/max notional, rate-limits, symbol allow-list |
| **Observability** | Prometheus metrics, Grafana dashboards, JSONL audit logs |
| **Governance** | Policy-driven pause/resume/promote/rollback |
| **Model Lifecycle** | Canary rollouts → live promotion → capital scaling |
| **Capital Allocator** | Auto-budgets capital by Sharpe ratio and PnL |
| **Alerting** | Telegram + local log notifications for anomalies |

---

### 🧩 Quickstart

```bash
git clone https://github.com/<you>/nautilus-hmm.git
cd nautilus-hmm
cp ops/env.example .env
docker compose up --build

Then open:
	•	OPS Dashboard: http://localhost:8002/pnl_dashboard.html
	•	Engine API: http://localhost:8003/docs

---

### 📡 Live API Highlights

Service	Endpoint	Description
Engine	/orders	Submit or query orders
Engine	/metrics	Prometheus feed
OPS	/dash/pnl	Aggregated PnL data
OPS	/stream	Real-time event feed (SSE)
OPS	/strategy/signal	Route signals to models
OPS	/strategy/weights	Adjust canary rollout ratios

---

### 🧠 Example Lifecycle
	1.	Deploy a new model as canary (10% weight).
	2.	OPS monitors live Sharpe and PnL.
	3.	Governance promotes if outperforming → 100% live.
	4.	Capital allocator expands its budget proportionally.
	5.	Alerts ping Telegram if performance degrades or risk triggers.
	6.	Full audit trail written to engine/logs/orders.jsonl.

---

### 📜 Prerequisites

- **Docker & Docker Compose** - For containerized deployment
- **Python 3.10+** - For local development
- **Trading API Keys** - Binance and/or IBKR credentials
- **Telegram Bot Token** - For alerting (optional)

### 🔧 Environment Setup

1. **Copy configuration:**
   ```bash
   cp ops/env.example .env
   # Edit .env with your API keys and settings
   ```

2. **Launch the system:**
   ```bash
   docker compose up --build
   ```

3. **Verify health:**
   ```bash
   curl http://localhost:8002/health  # OPS API
   curl http://localhost:8003/health  # Binance Engine
   curl http://localhost:8004/health  # IBKR Engine (if configured)
   ```

---

### 🎯 Key Features

#### Multi-Venue Execution
- **Binance Spot/Futures** via REST/WebSocket APIs
- **IBKR TWS/IB Gateway** integration
- **Unified Order Management** across all venues
- **Venue Risk Isolation** and failover logic

#### AI Strategy Stack
- **Hidden Markov Models** for market regime detection
- **Ensemble Learning** combining multiple approaches
- **Real-time Model Training** and adaptation
- **Canary Deployment** for safe ML rollouts

#### Live Capital Optimization
- **Sharpe-based Allocation** - capital flows to winners
- **Dynamic Rebalancing** every 30 seconds
- **Risk-adjusted Budgeting** with hard limits
- **Portfolio-level Optimization** across all models

#### Institutional Observability
- **Complete Performance Attribution** by model/venue
- **Real-time Dashboards** with live updates
- **Prometheus Metrics** for monitoring
- **Granular Audit Trails** for compliance

#### Autonomous Governance
- **Policy-driven Controls** via YAML configuration
- **Emergency Circuit Breakers** for risk events
- **Automated Model Lifecycle** management
- **Alert-driven Notifications** for anomalies

---

### 📊 Getting Started

1. **Deploy canary model:**
   ```bash
   curl -X POST http://localhost:8002/strategy/weights \
     -H "Content-Type: application/json" \
     -d '{"weights": {"hmm_v4_canary": 0.1}}'
   ```

2. **Monitor performance:**
   Open http://localhost:8002/pnl_dashboard.html

3. **Auto-promotion kicks in:**
   Watch logs for `[CANARY] 🚀 PROMOTED hmm_v4_canary`

4. **Capital auto-allocates:**
   Check `ops/capital_allocations.json` for quota increases

---

### 📈 Usage Examples

#### Trading Signal Submission
```bash
# Simple market order
curl -X POST http://localhost:8002/strategy/signal \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT.BINANCE",
    "side": "BUY",
    "quote": 100.0
  }'
```

#### Model Weight Adjustment
```bash
curl -X POST http://localhost:8002/strategy/weights \
  -H "Content-Type: application/json" \
  -d '{
    "weights": {
      "stable_model": 0.8,
      "test_model": 0.2
    }
  }'
```

#### Governance Pause
```bash
curl -X POST http://localhost:8002/kill \
  -H "X-OPS-TOKEN: dev-token" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

#### Extract Daily PnL Report
```bash
python ops/export_pnl.py
# Outputs: ops/exports/pnl_2024-12-19.csv
```

---

### 🏗️ Architecture Overview

```
                   ┌──────────────────────────────────────────┐
                   │              OPS Layer                   │
                   │──────────────────────────────────────────│
                   │                                          │
                   │  📡 Strategy Router   → routes signals    │
                   │  💰 Capital Allocator → sets model quotas │
                   │  🧠 Governance Daemon → acts on alerts    │
                   │  🧪 Canary Manager    → promotes models    │
                   │  📊 PnL Dashboard     → shows performance  │
                   │  🔔 Alert System      → Telegram/logs      │
                   │                                          │
                   └──────┬──────────────────────┬─────────────┘
                          │                      │
          (metrics / API) │                      │ (orders / PnL events)
                          │                      ▼
                   ┌──────┴────────────────────────────────────┐
                   │             Engine Layer                  │
                   │──────────────────────────────────────────│
                   │  ⚙️  Order Router + Risk Rails             │
                   │  💾 Persistence & Recovery                │
                   │  🔁 Idempotent API                        │
                   │  🧮 Prometheus Metrics + Audit Logs        │
                   │  📈 Reconciliation Daemon                 │
                   │  🧩 OMS Features (OCO, Trailing, C/R)      │
                   └──────┬───────────────────────────────┬────┘
                          │                               │
            ┌─────────────▼────────────┐     ┌────────────▼────────────┐
            │   Binance Engine         │     │   IBKR Engine           │
            │  (Spot / Futures)        │     │  (Equities / Options)   │
            └──────────────────────────┘     └─────────────────────────┘

                          ▲
                          │ SSE / Redis Bus
                          │
                   ┌──────┴─────────────────────┐
                   │     Real-Time Clients      │
                   │  (Dashboard / Terminal /   │
                   │   Telegram / Grafana)      │
                   └────────────────────────────┘
```

### 📁 Project Structure
```
nautilus-hmm/
├── ops/                    # Control plane services
│   ├── ops_api.py         # FastAPI server + endpoints
│   ├── strategy_router.py # Model routing & capital allocation
│   ├── canary_manager.py  # A/B testing evaluation
│   ├── capital_allocator.py# Live portfolio rebalancing
│   ├── pnl_dashboard.py   # Performance aggregation
│   └── static/            # HTML dashboard assets
├── engine/                 # Execution engines
│   ├── app.py             # FastAPI server + order management
│   ├── core/              # Risk rails, OMS features
│   ├── adapters/          # Venue-specific integrations
│   └── state/             # Persistence & recovery
├── strategies/             # AI strategy implementations
│   ├── hmm_policy/        # Markov chain models
│   └── ensemble_policy/   # Multi-model fusion
├── tests/                 # Comprehensive test suite
├── scripts/               # Utility scripts
└── docs/                  # Documentation
```

---

### 🔒 Security & Compliance

- **API Authentication:** Bearer tokens for control endpoints
- **Audit Logging:** Complete order and decision trails
- **Risk Limits:** Multi-layer position size controls
- **Access Control:** Environment-based credential management
- **Data Encryption:** API keys stored in secure environment variables

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Implement changes with tests
4. Ensure all tests pass: `pytest`
5. Submit a pull request with detailed description

See [DEV_GUIDE.md](DEV_GUIDE.md) for detailed development workflow.

---

### 📞 Support

- **Documentation:** See /docs folder for detailed guides
- **Issues:** Use GitHub issues for bugs/features
- **Discussions:** Use GitHub discussions for questions
- **Architecture:** Read [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)

---

### 📜 License

MIT (or your preferred license)
