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
