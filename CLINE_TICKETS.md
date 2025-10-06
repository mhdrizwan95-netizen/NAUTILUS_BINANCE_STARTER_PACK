# Cline Milestone Board — Nautilus HMM on Binance (Spot)
# Branch: feat/binance-hmm-v1

## M0 — Bootstrap
- Create venv, install deps (pyproject provided).

## M1 — Binance adapters (paper)
- Fill ops/run_paper.py to instantiate Binance Spot testnet data+exec clients and run engine.

## M2 — Features
- Implement compute_features() and rolling standardization. Add deque windows and per-session stats.

## M3 — ML service
- Implement real HMM + Policy; add /train and /partial_fit; persist to ml_service/model_store.

## M4 — Strategy
- Convert strategy.py to real Nautilus Strategy subclass; wire order placement and cache lookups. Add backtests/run_backtest.py using BacktestEngine.

## M5 — Guardrails & VWAP
- Enforce gates and implement VWAP anchoring & dynamic spread tolerance. Log reason codes.

## M7 — Paper demo
- 60 min unattended run; export CSV: trades, state timeline, guardrails.

## M8 — Live tiny
- Flip to live (BINANCE_IS_TESTNET=false); qty tiny; daily parquet rollups.

## M9 — Observability stack
- Add Prometheus /metrics, WebSocket live updates, Ops API kill/retrain/status; Grafana dashboard import ready.

## M10 — Slippage realism & data QA
- Queue-depth aware fills with vol/scatter/conf; data sanity guards; backtest slippage bands comparable to paper.

## M11 — Auto-retrain & Blue/Green
- Model versioning, hot-swappable serving, canary simulation, nightly retrain script with rollback.

## M12 — Multi-symbol + smarter risk
- **feat(m12): multi-symbol config + risk budget**; Update HMMPolicyConfig with SymbolConfig/RiskBudget dataclasses, multi-symbol support, dynamic sizing knobs.
- **feat(m12): guardrails expansion**; Add global budget, per-state DD, min notional, cooldown; log new reasons BUDGET/NOTIONAL/COOLDOWN_GLOBAL/DD.
- **feat(m12): dynamic sizing**; Implement policy with exp_edge = state_prior * conf, qty = k*|edge| / vol_bp, clipped to min/max with notional floor.
- **feat(m12): dual-symbol paper runner**; Subscribe BTC + ETH; maintain per-symbol state/pnl/exposure; pass new guard args; log symbol in CSVs.

## M13 — Hierarchical HMM (Macro/Micro)
- **feat(m13): H2 features** — implement `MacroMicroFeatures` and wire into strategy/backtest.
- **feat(m13): ML endpoints** — add `/train_h2`, `/infer_h2`, tag `h2-...`, persistence loaders.
- **feat(m13): policy gating** — macro→risk bias, integrate into guardrails thresholds and sizing with risk_bias (0.5/1.0/1.5).
- **feat(m13): artifacts** — add `macro_state` to `state_timeline.csv`, dashboard macro chart with separate histogram.
- **test(m13): h2 smoke** — unit test for train+infer path and CSV production validations.
- **feat(m13): prepare training** — offline script `backtests/prepare_h2_training.py` for Parquet→H2 data prep with clustering.

## M13.1 — Feature Expansion & Transition Intelligence
- **feat(m13.1): enhanced features** — implement and standardize new features (autocorr, vol clustering, imbalance momentum).
- **feat(m13.1): transition monitor** — live transition matrix, KL divergence, Prometheus export with drift detection.
- **feat(m13.1): dashboard panels** — new intent and transition drift charts with correlation visualizations.
- **test(m13.1): schema_v2 validation** — ensure training/inference consistency with enhanced features.

## M14 — Cross-Symbol Covariance Risk Control
- **feat(m14): covariance tracker** — implement rolling covariance & correlation matrix (BTC/ETH awareness).
- **feat(m14): portfolio risk manager** — exposure scaling + regime detection (lockstep/normal/divergent).
- **feat(m14): dashboard metrics** — correlation panels and alerts, portfolio vol visualization.
- **test(m14): backtest covariance sanity** — ensure correlation logic yields expected volatility scaling.

## M14.1 — Adaptive Correlation Regimes
- **feat(m14.1): multi-window correlation blend** — implement `MultiWindowCorr` and wire `lam` to vol_z.
- **feat(m14.1): adaptive clustering** — `CorrClusterer` with automatic k and stability smoothing.
- **feat(m14.1): cluster risk allocator** — equal-risk across clusters + global target volatility.
- **feat(m14.1): metrics & dashboard** — correlation entropy, cluster count/weights, corr heatmap.
- **test(m14.1): regime fixtures** — synthetic sequences that switch from low corr to high corr; assert exposure compression.

## M15 — Policy State-Action Feedback & Safe Online Learning
- **feat(m15): feedback logging** — `FeedbackLogger` with detailed trade/block event recording.
- **feat(m15): reward tables** — EMA reward tracking per state/action with serialization.
- **feat(m15): online trainer** — `TinyMLP` + safe `OnlineFineTuner` with gradient clipping/cooldown.
- **feat(m15): policy blending** — HMM confidence + learned rewards + online adaptation.
- **feat(m15): safety rails** — performance kill-switch, Ops API controls, rollback snapshots.
- **feat(m15): observability** — reward heatmaps, online adaptation metrics, performance tracking.
- **test(m15): safety & stability** — kill-switch activation, gradient clipping, rollback testing.
