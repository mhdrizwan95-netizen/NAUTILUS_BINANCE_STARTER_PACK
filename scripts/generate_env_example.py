from __future__ import annotations

from pathlib import Path
import sys
from typing import Dict, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.config.defaults import ALL_DEFAULTS

SECTIONS: Dict[str, Iterable[str]] = {
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
    ],
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
    "Deprecated (aliases)": [
        "SOCIAL_SENTIMENT_ENABLED",
        "SOCIAL_SENTIMENT_SOURCES",
    ],
}

COMMENTS = {
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
    "TREND_SYMBOLS": "Optional override; empty or '*' falls back to TRADE_SYMBOLS.",
    "SCALP_SYMBOLS": "Optional override for scalping universe.",
    "MOMENTUM_RT_SYMBOLS": "Optional override for momentum universe.",
    "MEME_SENTIMENT_SOURCES": "CSV of event sources to react to (twitter_firehose,dex_whale,binance_listings).",
    "MEME_SENTIMENT_DENY_KEYWORDS": "Comma-separated keywords to ignore.",
    "MEME_SENTIMENT_QUOTES": "Preferred quote assets when selecting trading pairs.",
    "SYMBOL_SCANNER_UNIVERSE": "Universe preset or CSV list; '*' falls back to TRADE_SYMBOLS.",
    "SYMBOL_SCANNER_STATE_PATH": "State file for scanner selections.",
    "SOCIAL_SENTIMENT_ENABLED": "DEPRECATED: use MEME_SENTIMENT_ENABLED.",
    "SOCIAL_SENTIMENT_SOURCES": "DEPRECATED: use MEME_SENTIMENT_SOURCES.",
}


def _render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def main() -> None:
    lines = ["# Autogenerated by scripts/generate_env_example.py", "# Update this file via the script to keep defaults in sync.\n"]
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
