from __future__ import annotations

from pathlib import Path
import runpy
from typing import Dict, Iterable, Set

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PATH = ROOT / "engine" / "config" / "defaults.py"

defaults_namespace = runpy.run_path(str(DEFAULTS_PATH))
try:
    ALL_DEFAULTS = defaults_namespace["ALL_DEFAULTS"]
except KeyError as exc:
    available = ", ".join(sorted(defaults_namespace))
    raise RuntimeError(
        f"defaults file at {DEFAULTS_PATH} did not define ALL_DEFAULTS; found keys: {available or '<none>'}"
    ) from exc

SECTIONS: Dict[str, Iterable[str]] = {
    "Engine": ["EVENTBUS_MAX_WORKERS"],
    "Global": ["TRADE_SYMBOLS", "DRY_RUN"],
    "Risk": [
        "TRADING_ENABLED",
        "MIN_NOTIONAL_USDT",
        "MAX_NOTIONAL_USDT",
        "MAX_ORDERS_PER_MIN",
        "DUST_THRESHOLD_USD",
        "EXPOSURE_CAP_SYMBOL_USD",
        "EXPOSURE_CAP_TOTAL_USD",
        "EXPOSURE_CAP_VENUE_USD",
        "VENUE_ERROR_BREAKER_PCT",
        "VENUE_ERROR_WINDOW_SEC",
        "EQUITY_FLOOR_USD",
        "EQUITY_DRAWDOWN_LIMIT_PCT",
        "EQUITY_COOLDOWN_SEC",
        "MARGIN_ENABLED",
        "MARGIN_MIN_LEVEL",
        "MARGIN_MAX_LIABILITY_USD",
        "MARGIN_MAX_LEVERAGE",
        "OPTIONS_ENABLED",
        "SOFT_BREACH_ENABLED",
        "SOFT_BREACH_TIGHTEN_SL_PCT",
        "SOFT_BREACH_BREAKEVEN_OK",
        "SOFT_BREACH_CANCEL_ENTRIES",
        "SOFT_BREACH_LOG_ORDERS",
    ],
    "Broker": ["IBKR_ENABLED"],
    "Trend Strategy": [
        "TREND_ENABLED",
        "TREND_DRY_RUN",
        "TREND_SYMBOLS",
        "TREND_FETCH_LIMIT",
        "TREND_REFRESH_SEC",
        "TREND_ATR_LENGTH",
        "TREND_ATR_STOP_MULT",
        "TREND_ATR_TARGET_MULT",
        "TREND_SWING_LOOKBACK",
        "TREND_RSI_LONG_MIN",
        "TREND_RSI_LONG_MAX",
        "TREND_RSI_EXIT",
        "TREND_RISK_PCT",
        "TREND_MIN_QUOTE_USD",
        "TREND_FALLBACK_EQUITY",
        "TREND_COOLDOWN_BARS",
        "TREND_ALLOW_SHORTS",
        "TREND_AUTO_TUNE_ENABLED",
        "TREND_AUTO_TUNE_MIN_TRADES",
        "TREND_AUTO_TUNE_INTERVAL",
        "TREND_AUTO_TUNE_HISTORY",
        "TREND_AUTO_TUNE_WIN_LOW",
        "TREND_AUTO_TUNE_WIN_HIGH",
        "TREND_AUTO_TUNE_STOP_MIN",
        "TREND_AUTO_TUNE_STOP_MAX",
        "TREND_AUTO_TUNE_STATE_PATH",
        "TREND_PRIMARY_INTERVAL",
        "TREND_PRIMARY_FAST",
        "TREND_PRIMARY_SLOW",
        "TREND_PRIMARY_RSI",
        "TREND_SECONDARY_INTERVAL",
        "TREND_SECONDARY_FAST",
        "TREND_SECONDARY_SLOW",
        "TREND_SECONDARY_RSI",
        "TREND_REGIME_INTERVAL",
        "TREND_REGIME_FAST",
        "TREND_REGIME_SLOW",
        "TREND_REGIME_RSI",
    ],
    "Scalping": [
        "SCALP_ENABLED",
        "SCALP_DRY_RUN",
        "SCALP_SYMBOLS",
        "SCALP_WINDOW_SEC",
        "SCALP_MIN_TICKS",
        "SCALP_MIN_RANGE_BPS",
        "SCALP_LOWER_THRESHOLD",
        "SCALP_UPPER_THRESHOLD",
        "SCALP_RSI_LENGTH",
        "SCALP_RSI_BUY",
        "SCALP_RSI_SELL",
        "SCALP_STOP_BPS",
        "SCALP_TP_BPS",
        "SCALP_QUOTE_USD",
        "SCALP_COOLDOWN_SEC",
        "SCALP_ALLOW_SHORTS",
        "SCALP_PREFER_FUTURES",
        "SCALP_SIGNAL_TTL_SEC",
        "SCALP_MAX_SIGNALS_PER_MIN",
        "SCALP_IMBALANCE_THRESHOLD",
        "SCALP_MAX_SPREAD_BPS",
        "SCALP_MIN_DEPTH_USD",
        "SCALP_MOMENTUM_TICKS",
        "SCALP_FEE_BPS",
        "SCALP_BOOK_STALE_SEC",
    ],
    "Momentum (Real-Time)": [
        "MOMENTUM_RT_ENABLED",
        "MOMENTUM_RT_DRY_RUN",
        "MOMENTUM_RT_SYMBOLS",
        "MOMENTUM_RT_WINDOW_SEC",
        "MOMENTUM_RT_BASELINE_SEC",
        "MOMENTUM_RT_MOVE_THRESHOLD_PCT",
        "MOMENTUM_RT_VOLUME_SPIKE_RATIO",
        "MOMENTUM_RT_STOP_PCT",
        "MOMENTUM_RT_TRAIL_PCT",
        "MOMENTUM_RT_TP_PCT",
        "MOMENTUM_RT_MIN_TICKS",
        "MOMENTUM_RT_COOLDOWN_SEC",
        "MOMENTUM_RT_QUOTE_USD",
        "MOMENTUM_RT_ALLOW_SHORTS",
        "MOMENTUM_RT_PREFER_FUTURES",
    ],
    "Meme Sentiment": [
        "MEME_SENTIMENT_ENABLED",
        "MEME_SENTIMENT_DRY_RUN",
        "MEME_SENTIMENT_RISK_PCT",
        "MEME_SENTIMENT_STOP_PCT",
        "MEME_SENTIMENT_TP_PCT",
        "MEME_SENTIMENT_TRAIL_PCT",
        "MEME_SENTIMENT_FALLBACK_EQUITY",
        "MEME_SENTIMENT_NOTIONAL_MIN",
        "MEME_SENTIMENT_NOTIONAL_MAX",
        "MEME_SENTIMENT_MIN_PRIORITY",
        "MEME_SENTIMENT_MIN_SCORE",
        "MEME_SENTIMENT_MIN_MENTIONS",
        "MEME_SENTIMENT_MIN_VELOCITY",
        "MEME_SENTIMENT_MAX_CHASE_PCT",
        "MEME_SENTIMENT_MAX_SPREAD_PCT",
        "MEME_SENTIMENT_COOLDOWN_SEC",
        "MEME_SENTIMENT_LOCK_SEC",
        "MEME_SENTIMENT_DENY_KEYWORDS",
        "MEME_SENTIMENT_SOURCES",
        "MEME_SENTIMENT_QUOTES",
        "MEME_SENTIMENT_METRICS_ENABLED",
        "MEME_SENTIMENT_PUBLISH_TOPIC",
        "MEME_SENTIMENT_DEFAULT_MARKET",
    ],
    "Symbol Scanner": [
        "SYMBOL_SCANNER_ENABLED",
        "SYMBOL_SCANNER_UNIVERSE",
        "SYMBOL_SCANNER_INTERVAL_SEC",
        "SYMBOL_SCANNER_INTERVAL",
        "SYMBOL_SCANNER_LOOKBACK",
        "SYMBOL_SCANNER_TOP_N",
        "SYMBOL_SCANNER_MIN_VOLUME_USD",
        "SYMBOL_SCANNER_MIN_ATR_PCT",
        "SYMBOL_SCANNER_WEIGHT_RET",
        "SYMBOL_SCANNER_WEIGHT_TREND",
        "SYMBOL_SCANNER_WEIGHT_VOL",
        "SYMBOL_SCANNER_MIN_MINUTES_BETWEEN_RESELECT",
        "SYMBOL_SCANNER_STATE_PATH",
    ],
    "Autotrain Shared": [
        "LEDGER_DB",
    ],
    "Data Ingestion": [
        "DATA_LANDING",
        "EXCHANGE",
        "SYMBOLS",
        "TIMEFRAME",
        "BATCH_LIMIT",
        "START_TS",
        "END_TS",
        "SLEEP_MS",
        "LOG_LEVEL",
    ],
    "ML Service": [
        "DATA_DIR",
        "MODEL_DIR",
        "REGISTRY_DIR",
        "CURRENT_SYMLINK",
        "HMM_STATES",
        "TRAIN_WINDOW_DAYS",
        "EXACTLY_ONCE",
        "TRAIN_MIN_POINTS",
        "PROMOTION_MIN_DELTA",
        "KEEP_N_MODELS",
        "AUTO_PROMOTE",
        "DELETE_AFTER_PROCESS",
        "RETRAIN_CRON",
        "REQUIRE_AUTH",
        "JWT_ALG",
        "JWT_SECRET",
        "JWT_PUBLIC_KEY",
        "LOG_LEVEL",
    ],
    "Param Controller": [
        "PC_DB",
        "EPSILON",
        "L2",
        "MAX_PRESETS",
        "LOG_LEVEL",
    ],
    "Backtest Runner": [
        "RESEARCH_DIR",
        "DATA_INCOMING",
        "ML_SERVICE",
        "PARAM_CONTROLLER",
        "SYMBOLS",
        "TIMEFRAME",
        "CHUNK_ROWS",
        "START_TS",
        "END_TS",
        "TRAIN_CRON_MINUTES",
        "PROMOTE",
        "EXACTLY_ONCE",
        "TRAIN_MIN_POINTS",
        "FEE_BP",
        "SLIPPAGE_BP",
        "MAX_STEPS",
        "LOG_LEVEL",
    ],
    "Deprecated (aliases)": [
        "SOCIAL_SENTIMENT_ENABLED",
        "SOCIAL_SENTIMENT_SOURCES",
    ],
}

SECTION_KEYS: Set[str] = {key for keys in SECTIONS.values() for key in keys}

missing_defaults = sorted(key for key in ALL_DEFAULTS if key not in SECTION_KEYS)
if missing_defaults:
    raise RuntimeError(
        "Missing keys in .env example generator; add them to SECTIONS: "
        + ", ".join(missing_defaults)
    )

unknown_keys = sorted(key for key in SECTION_KEYS if key not in ALL_DEFAULTS)
if unknown_keys:
    raise RuntimeError(
        "Generator references keys not present in ALL_DEFAULTS: "
        + ", ".join(unknown_keys)
    )

COMMENTS = {
    "EVENTBUS_MAX_WORKERS": "Thread pool size for sync EventBus handlers.",
    "TRADE_SYMBOLS": "Comma list of BASEQUOTE symbols (e.g., BTCUSDT,ETHUSDT) or '*' for allow-all.",
    "DRY_RUN": "Set to true to avoid placing live orders.",
    "MIN_NOTIONAL_USDT": "Smallest order notional (USD/USDT).",
    "MAX_NOTIONAL_USDT": "Largest order notional allowed per trade.",
    "MAX_ORDERS_PER_MIN": "Rate limit on submitted orders per minute.",
    "DUST_THRESHOLD_USD": "Balances below this threshold are ignored as dust.",
    "EXPOSURE_CAP_SYMBOL_USD": "Cap on total exposure per symbol.",
    "EXPOSURE_CAP_TOTAL_USD": "Cap on total exposure across all symbols.",
    "EXPOSURE_CAP_VENUE_USD": "Cap on venue-wide exposure (spot+futures).",
    "VENUE_ERROR_BREAKER_PCT": "Error breaker trip percentage (venue health).",
    "VENUE_ERROR_WINDOW_SEC": "Window for venue error breaker evaluation.",
    "EQUITY_FLOOR_USD": "Trading pauses if equity falls below this.",
    "EQUITY_DRAWDOWN_LIMIT_PCT": "Max daily drawdown before cooldown engages.",
    "EQUITY_COOLDOWN_SEC": "Cooldown duration after hitting drawdown limit.",
    "MARGIN_ENABLED": "Allow submitting margin orders.",
    "OPTIONS_ENABLED": "Allow submitting options orders.",
    "SOFT_BREACH_ENABLED": "Enable soft risk-breach mitigations.",
    "SOFT_BREACH_TIGHTEN_SL_PCT": "Tighten stop-loss to this pct when a soft breach triggers.",
    "SOFT_BREACH_BREAKEVEN_OK": "Allow tightening stops to breakeven even if above target pct.",
    "SOFT_BREACH_CANCEL_ENTRIES": "Cancel open entry orders when a soft breach occurs.",
    "SOFT_BREACH_LOG_ORDERS": "Log order details when soft breach protection activates.",
    "IBKR_ENABLED": "Enable Interactive Brokers integration.",
    "TREND_SYMBOLS": "Optional override; empty or '*' falls back to TRADE_SYMBOLS.",
    "SCALP_SYMBOLS": "Optional override for scalping universe.",
    "MOMENTUM_RT_SYMBOLS": "Optional override for momentum universe.",
    "MEME_SENTIMENT_SOURCES": "CSV of event sources to react to (twitter_firehose,dex_whale,binance_listings).",
    "MEME_SENTIMENT_DENY_KEYWORDS": "Comma-separated keywords to ignore.",
    "MEME_SENTIMENT_QUOTES": "Preferred quote assets when selecting trading pairs.",
    "SYMBOL_SCANNER_UNIVERSE": "Universe preset or CSV list; '*' falls back to TRADE_SYMBOLS.",
    "SYMBOL_SCANNER_ENABLED": "Enable the dynamic symbol scanner; authoritative universe when true.",
    "SYMBOL_SCANNER_STATE_PATH": "State file for scanner selections.",
    "SOCIAL_SENTIMENT_ENABLED": "DEPRECATED: use MEME_SENTIMENT_ENABLED.",
    "SOCIAL_SENTIMENT_SOURCES": "DEPRECATED: use MEME_SENTIMENT_SOURCES.",
    "LEDGER_DB": "SQLite ledger shared by ingestion, training, and backtesting services.",
    "DATA_LANDING": "Staging directory for downloaded OHLCV files.",
    "EXCHANGE": "Source exchange identifier (ccxt).",
    "SYMBOLS": "Comma-separated trading pairs to ingest or simulate.",
    "TIMEFRAME": "Candlestick interval requested from the exchange.",
    "BATCH_LIMIT": "Maximum candles fetched per ingest request.",
    "START_TS": "Initial timestamp (ms) used when no watermark exists.",
    "END_TS": "Optional end timestamp (ms) to cap ingestion (0 = now).",
    "SLEEP_MS": "Extra delay between requests in milliseconds to avoid rate limits.",
    "DATA_DIR": "Shared data volume mounted into ml_service containers.",
    "MODEL_DIR": "Root directory for persisted models.",
    "REGISTRY_DIR": "Location where model versions are stored.",
    "CURRENT_SYMLINK": "Symlink pointing to the active model version.",
    "HMM_STATES": "Default number of hidden states for the HMM trainer.",
    "TRAIN_WINDOW_DAYS": "Lookback window (days) of data used for training.",
    "EXACTLY_ONCE": "Train each bar at most once (true) or use a sliding window (false).",
    "TRAIN_MIN_POINTS": "Minimum observations required before fitting a model.",
    "PROMOTION_MIN_DELTA": "Minimum improvement required to promote a model.",
    "KEEP_N_MODELS": "Number of historical models to retain in the registry.",
    "AUTO_PROMOTE": "Automatically promote models that beat the current metric.",
    "DELETE_AFTER_PROCESS": "Remove raw files after a successful training round.",
    "RETRAIN_CRON": "Cron expression controlling the scheduler retrain cadence.",
    "REQUIRE_AUTH": "Toggle JWT authentication for API endpoints.",
    "JWT_ALG": "JWT signing algorithm (HS/RS/ES variants).",
    "JWT_SECRET": "Shared secret for HS* algorithms; leave blank for RS/ES.",
    "JWT_PUBLIC_KEY": "Public key for RS/ES algorithms; newline separated.",
    "PC_DB": "SQLite database storing presets, bandit history, and outcomes.",
    "EPSILON": "Exploration rate used as a fallback to linear Thompson Sampling.",
    "L2": "Ridge regularisation applied to the linear bandit posterior.",
    "MAX_PRESETS": "Safety cap on simultaneously active parameter presets.",
    "RESEARCH_DIR": "Base directory containing historical CSVs for simulation.",
    "DATA_INCOMING": "Landing directory where simulated chunks are written.",
    "ML_SERVICE": "Base URL for the training/inference service used during sim.",
    "PARAM_CONTROLLER": "Base URL for the parameter controller service.",
    "CHUNK_ROWS": "Number of rows included in each simulated ingest batch.",
    "END_TS": "Optional end timestamp (ms) to limit simulation range (0 = all).",
    "TRAIN_CRON_MINUTES": "Minutes between retraining events during simulation.",
    "PROMOTE": "Allow simulator to promote better models automatically.",
    "FEE_BP": "Per-side fee assumptions in basis points for execution.",
    "SLIPPAGE_BP": "Per-side slippage assumptions in basis points.",
    "MAX_STEPS": "Safety cap on simulation iterations.",
    "LOG_LEVEL": "Log level override for the respective service.",
}


def _render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def main() -> None:
    lines = [
        "# Autogenerated by scripts/generate_env_example.py",
        "# Update this file via the script to keep defaults in sync.\n",
    ]
    for title, keys in SECTIONS.items():
        lines.append(f"### {title}")
        for key in keys:
            comment = COMMENTS.get(key)
            if comment:
                lines.append(f"# {comment}")
            value = ALL_DEFAULTS.get(key, "")
            if title == "Deprecated (aliases)":
                lines.append(f"#{key}={_render_value(value)}")
            else:
                lines.append(f"{key}={_render_value(value)}")
        lines.append("")
    Path(".env.example").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
