# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Import smoke tests to guard the canonical `engine.strategies.policy_hmm`
  and `engine.strategies.ensemble_policy` entry points.

### Removed
- Legacy `strategies/hmm_policy/` skeleton in favour of the unified
  `engine/strategies` implementations.
- Obsolete `ops/run_live.py` launcher now superseded by `engine/app.py` and
  the scheduler service.
- Dead `scripts/simulate_venue_errors.py` helper flagged by the dead code guard.

## [1.1.0] - 2025-12-13

### 🚀 Dynamic Architecture & Experience Learning (Phase 5)

This release activates the "brain" of the organism, allowing it to explore new markets and learn from experience.

### ✨ New Features
- **Dynamic User Universe**: `SymbolScanner` now autonomously discovers high-momentum/volume assets (e.g., `FOLKSUSDT`) and injects them into the trading loop.
- **Reinforcement Learning (RL) Loop**: `ParamControllerBridge` wires realized PnL back to the Bandit Model, enabling the system to learn optimal risk parameters (Confidence Thresholds, Cooldowns) over time.
- **Adaptive Risk Rails**: `RiskRails` allowlist now dynamically expands to include scanned symbols via `universe.update` events.

### 🛠 Fixes & Improvements
- **Event Bus Wiring**: Fixed `SymbolScanner` event publishing by switching to thread-safe `BUS.fire()` logic.
- **User Stream Stability**: Resolved `401 Unauthorized` issues preventing PnL tracking (IP Whitelist).
- **Frontend Telemetry**: Fixed "MISSING" IDs in the dashboard and "NULL" PnL display.
- **Strategy Tuning**: Enforced RRR > 2.5 for Trend and Scalp strategies to prioritize expectancy.

### ⚠️ Breaking Changes
- `SYMBOL_SCANNER_ENABLED` defaults to `true`.
- Requires updated `BINANCE_API_KEY` permissions (IP Whitelist).

---

## [1.0.0] - 2025-10-11

🧠 Nautilus HMM v1.0.0

Autonomous Multi-Venue Trading System — Stable Architecture Release

---

### 🚀 Overview

This release marks the first production-grade milestone (M15) of the Nautilus trading ecosystem — a fully autonomous, self-regulating trading stack integrating Binance and IBKR engines with adaptive AI strategy governance.

The system now executes, monitors, audits, and optimizes itself end-to-end with no human intervention required during normal operation.

---

### 🧩 Core Highlights

#### ⚙️ Engine Layer
- Unified FastAPI trading engines for Binance and IBKR
- Full risk-rail enforcement (min/max notional, rate-limits, toggle)
- OCO + Trailing Stop order logic
- Persistence & crash-safe snapshots (engine/state/portfolio.json)
- Prometheus metrics + structured audit logging

#### 🧠 OPS Layer
- Strategy router with multi-model weighting
- Canary deployments and auto-promotion logic
- Governance daemon with YAML-defined policies
- Capital allocator dynamically adjusts model budgets by Sharpe/PnL
- PnL dashboard + daily CSV export
- Real-time event bus (SSE/Redis-ready)
- Alert & anomaly system with Telegram integration

---

### 📊 Observability
- Unified Prometheus endpoint across all venues
- Grafana-ready dashboards for PnL, latency, fill rate, Sharpe
- JSONL audit trail for all orders and governance actions
- /dash/pnl live REST feed + auto-refresh HTML dashboard

---

### 🧱 Governance Intelligence
- Event-driven governance reacts to risk.reject, metrics.update, and alert topics
- Actions:
  - pause_trading / resume_trading
  - reduce_exposure
  - promote_model
- Self-healing reconciliation restores live order state on restart
- Full feedback loop:
  Signal → Execution → Metrics → Governance → Capital → Signal

---

### 🪙 Dynamic Capital Allocation
- Policy-based allocator (ops/capital_policy.json)
- Expands or contracts per-model capital quotas automatically
- Safely clips trade sizes to budget limits
- Writes ops/capital_allocations.json for visibility

---

### 🧩 Documentation

New comprehensive documentation suite:

```
docs/
 ├── README.md
 ├── SYSTEM_DESIGN.md
 ├── OPS_RUNBOOK.md
 └── DEV_GUIDE.md
```

Includes full ASCII architecture diagrams, data flow, and operational procedures.

---

### 🧪 Testing & Stability
- 80+ pytest suites across risk, metrics, idempotency, canary, allocator
- Integration tests validate engine/OPS handshake
- Continuous run verified under simulated markets

---

### 📦 Deployment

```bash
cp ops/env.example .env
docker compose up --build
```

Open:
- OPS dashboard → http://localhost:8002/pnl_dashboard.html
- Engine API → http://localhost:8003/docs

---

### 🔖 Summary

| Category          | State     |
|-------------------|-----------|
| Trading Engines   | ✅ Stable |
| Risk Management   | ✅ Hardened |
| Observability     | ✅ Complete |
| Governance        | ✅ Autonomous |
| Model Lifecycle   | ✅ Self-evolving |
| Documentation     | ✅ Comprehensive |

---

"The system no longer waits for instructions — it learns, acts, and protects itself."
