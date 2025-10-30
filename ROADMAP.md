# Roadmap

## Backtest Harness (in progress)

The legacy backtest stubs were removed. Shipping a real harness requires the following milestones:

- [ ] Market data adapters that stream historical klines/trades into the engine without mutating live state.
- [ ] Deterministic replay clock that mirrors engine scheduling and supports seeded randomness for reproducibility.
- [ ] Fill/fee/slippage model to simulate venue execution accurately enough for strategy validation.
- [ ] Portfolio accounting hooks that write to an isolated ledger for backtest runs.
- [ ] CLI/automation surface (e.g., `scripts/run_backtest.py`) wired to the new infrastructure once ready.
- [ ] Regression suite that exercises representative strategies (HMM ensemble, trend, scalping, event-driven).

Track progress in the issue tracker or by checking this file. Until these boxes are checked, treat any research notebooks or scripts as unsupported examples only.
