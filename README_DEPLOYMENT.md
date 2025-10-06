Calibration Notebook: see notebooks/M15_Calibration.ipynb for M15 reward/online-learning diagnostics.

### Calibration Utilities

#### M15 Calibration (FAST)
Run a quick backtest to generate feedback, then produce calibration PNGs:
    ./ops/calibrate_fast.sh
Outputs → data/processed/calibration/*.png

#### M15 Calibration (PAPER)
Run paper trading on testnet for 15 minutes, then calibrate:
    ./ops/calibrate_paper.sh 900
Set BINANCE_IS_TESTNET=true and TRADING_ENABLED=true in your environment or .env.

#### M15: Headless calibration (requires existing feedback_log.csv)
Run: `python ops/calibrate_policy.py`
Outputs → `data/processed/calibration/{reward_heatmap.png, policy_boundary.png, rolling_winrate.png}`

### M16 Reinforcement Fine-Tuning
Refines the policy using recency-weighted, risk-adjusted rewards and off-policy correction.

Run:
    ./ops/m16_reinforce.sh

Flow:
    feedback_log.csv → m16_reinforce.py → policy_vNext.joblib → canary_sim → /promote

Outputs:
    data/processed/m16/{learning_curve.png, drift_vs_reward.png, metrics.prom}
Grafana:
    Scrape metrics.prom (file_sd or sidecar) to plot m16_avg_reward, m16_entropy, m16_winrate.

### M18 Multi-Symbol Mode
To activate shared risk allocation:
    import risk.covariance_allocator as cov
    allocator = cov.CovarianceAllocator(window=500, target_var=0.0001)
    strategy.enable_covariance_allocator(allocator)
Diagnostics:
    python ops/m18_cov_diag.py
