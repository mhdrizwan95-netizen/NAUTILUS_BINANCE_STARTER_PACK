# Feature Flags

One-page index of important environment variables. Defaults live in `engine/config/defaults.py` and surface in `.env.example`.
Start new modules in dry-run mode, watch Prometheus/telemetry, then flip them live with conservative sizing.

## Core Engine Controls
- `TRADING_ENABLED` — master switch for placing live orders (leave `false` while validating signals).
- `DRY_RUN` — global dry-run; when `true` the engine logs intent without routing to venues.
- `TRADE_SYMBOLS` — global allowlist for all strategies. Use `*` to allow every discovered symbol or provide a comma list (e.g. `BTCUSDT,ETHUSDT`).
- `MIN_NOTIONAL_USDT`, `MAX_NOTIONAL_USDT` — global order size rails enforced by `RiskRails`.
- `EXPOSURE_CAP_SYMBOL_USD`, `EXPOSURE_CAP_TOTAL_USD`, `MAX_CONCURRENT_TRADES` — portfolio wide exposure limits.
- `RISK_PER_TRADE_PCT`, `DAILY_DRAWDOWN_STOP_PCT` — default position sizing and kill-switch thresholds.

## Systematic Strategy Loop (MA + HMM Ensemble)
- `STRATEGY_ENABLED`, `STRATEGY_DRY_RUN` — enable the legacy MA + HMM scheduler that runs at a fixed cadence.
- `STRATEGY_INTERVAL_SEC`, `STRATEGY_LOOKBACK_SEC` — cadence and lookback horizon for the MA sweep.
- `STRATEGY_SYMBOLS` (deprecated) — historical allowlist. Prefer `TRADE_SYMBOLS` or the per-strategy lists below.
- `ENSEMBLE_ENABLED`, `ENSEMBLE_WEIGHTS`, `ENSEMBLE_MIN_CONF` — combine MA and HMM signals via confidence-weighted fusion.
- `HMM_ENABLED`, `HMM_MODEL_PATH`, `HMM_WINDOW`, `HMM_SLIPPAGE_BPS` — load and tune the HMM policy head.

## Systematic Tick Strategies
- `TREND_ENABLED`, `TREND_DRY_RUN` — adaptive SMA/RSI/ATR trend follower (`engine/strategies/trend_follow.py`).
- `TREND_SYMBOLS` — optional comma list; blank or `*` falls back to `TRADE_SYMBOLS`.
- `TREND_TIMEFRAME`, `TREND_FETCH_LIMIT`, `TREND_MA_FAST`, `TREND_MA_SLOW`, `TREND_RSI_LEN`, `TREND_RSI_ENTRY_MIN`, `TREND_RSI_EXIT_MAX`, `TREND_ATR_LEN`, `TREND_ATR_STOP_MULT`, `TREND_RISK_PER_TRADE_PCT` — shape the indicator windows, stop multiplier, and sizing.
- `TREND_AUTO_TUNE_ENABLED`, `TREND_AUTO_TUNE_MIN_TRADES`, `TREND_AUTO_TUNE_INTERVAL`, `TREND_AUTO_TUNE_STOP_MIN`, `TREND_AUTO_TUNE_STOP_MAX`, `TREND_AUTO_TUNE_WIN_LOW`, `TREND_AUTO_TUNE_WIN_HIGH` — optional closed-loop tuner that nudges RSI and ATR parameters based on win rate.

- `SCALP_ENABLED`, `SCALP_DRY_RUN` — fast mean-reversion scalper that operates on aggregated ticks (`engine/strategies/scalping.py`).
- `SCALP_SYMBOLS` — optional override (otherwise uses `TRADE_SYMBOLS`).
- `SCALP_WINDOW_SEC`, `SCALP_MIN_TICKS`, `SCALP_TAKE_PROFIT_PCT`, `SCALP_STOP_LOSS_PCT`, `SCALP_ORDER_SIZE_USD`, `SCALP_MAX_CONCURRENT`, `SCALP_COOLDOWN_SEC`, `SCALP_MAX_SPREAD_BPS` — tune the scalper window, exit targets, and concurrency.

- `MOMENTUM_RT_ENABLED`, `MOMENTUM_RT_DRY_RUN` — breakout/momentum monitor that reacts to fast moves (`engine/strategies/momentum_realtime.py`).
- `MOMENTUM_RT_SYMBOLS` — optional per-strategy list; blank/`*` uses the global allowlist.
- `MOMENTUM_RT_WINDOW_SEC`, `MOMENTUM_RT_MOVE_PCT`, `MOMENTUM_RT_VOLUME_MULT`, `MOMENTUM_RT_TP_PCT`, `MOMENTUM_RT_SL_PCT`, `MOMENTUM_RT_TRAILING_PCT`, `MOMENTUM_RT_RISK_PER_TRADE_PCT`, `MOMENTUM_RT_COOLDOWN_SEC` — set the detection window, move threshold, and trailing stops.

## Event-Driven Strategies (EventBus `events.external_feed`)
- `LISTING_SNIPER_ENABLED`, `LISTING_SNIPER_DRY_RUN` — reacts to Binance "will list" announcements (`engine/strategies/listing_sniper.py`).
- `LISTING_SNIPER_SOURCES`, `LISTING_SNIPER_BLACKLIST`, `LISTING_SNIPER_MAX_NOTIONAL_USD`, `LISTING_SNIPER_COOLDOWN_SEC` — control announcement sources, deny lists, sizing, and per-symbol cooldowns.

- `MEME_SENTIMENT_ENABLED`, `MEME_SENTIMENT_DRY_RUN` — routes social hype events to the meme coin strategy (`engine/strategies/meme_coin_sentiment.py`).
- `MEME_SENTIMENT_SOURCES`, `MEME_SENTIMENT_MIN_SIGNAL`, `MEME_SENTIMENT_MAX_POSITION_USD`, `MEME_SENTIMENT_COOLDOWN_SEC` — required sources, signal threshold, per-trade cap, and cooldown.
- `SOCIAL_SENTIMENT_ENABLED`, `SOCIAL_SENTIMENT_SOURCES` — deprecated aliases; present for backwards compatibility and emit warnings when used.

- `AIRDROP_PROMO_ENABLED`, `AIRDROP_PROMO_DRY_RUN` — listens for exchange promotion events (`engine/strategies/airdrop_promo.py`).
- `AIRDROP_PROMO_SOURCES`, `AIRDROP_PROMO_MAX_NOTIONAL_USD`, `AIRDROP_PROMO_COOLDOWN_SEC` — configure signal feeds, notional cap, and cooldowns.

- `SYMBOL_SCANNER_ENABLED`, `SYMBOL_SCANNER_UNIVERSE`, `SYMBOL_SCANNER_REFRESH_MIN`, `SYMBOL_SCANNER_TOP_N` — maintain a ranked shortlist of tradeable symbols for the systematic stack.

## Protective Guards & Risk Mitigation
- **Depeg Guard**: `DEPEG_GUARD_ENABLED`, `DEPEG_THRESHOLD_PCT`, `DEPEG_CONFIRM_WINDOWS`, `DEPEG_ACTION_COOLDOWN_MIN`, `DEPEG_EXIT_RISK`, `DEPEG_SWITCH_QUOTE`.
- **Funding Guard**: `FUNDING_GUARD_ENABLED`, `FUNDING_SPIKE_THRESHOLD`, `FUNDING_TRIM_PCT`, `FUNDING_HEDGE_RATIO`.
- **Stop Validator**: `STOP_VALIDATOR_ENABLED`, `STOP_VALIDATOR_INTERVAL_SEC`, `STOP_VALIDATOR_GRACE_SEC`, `STOP_VALIDATOR_REPAIR`, `STOPVALIDATOR_REPAIR_TP`, `STOPVAL_NOTIFY_ENABLED`, `STOPVAL_NOTIFY_DEBOUNCE_SEC`.
- **Auto cutback/mute**: `AUTO_CUTBACK_ENABLED`, `AUTO_CUTBACK_SIZE_MULT`, `AUTO_CUTBACK_DURATION_MIN`, `AUTO_MUTE_SCALP_THRESHOLD`, `AUTO_MUTE_SCALP_WINDOW_MIN`, `AUTO_MUTE_SCALP_DURATION_MIN`.

## Execution & Market Access
- `SPOT_TAKER_MAX_SLIP_BPS`, `FUT_TAKER_MAX_SLIP_BPS` — slippage caps for taker orders.
- `SCALP_MAKER_SHADOW`, `MAKER_PRICE_IMPROVE_BPS` — optional maker shadowing knobs.
- `EXEC_FILLS_LISTENER_ENABLED` — stream venue fills via WebSocket.
- `WS_HEALTH_ENABLED`, `WS_DISCONNECT_ALERT_SEC`, `WS_RECONNECT_BACKOFF_MS` — WebSocket health monitoring.

## Telemetry & Notifications
- `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — core Telegram alerting.
- `TELEGRAM_BRIDGE_ENABLED` — relay internal bus events to Telegram for debugging.
- `HEALTH_TG_ENABLED`, `HEALTH_DEBOUNCE_SEC` — health summaries.
- `DIGEST_INTERVAL_MIN`, `DIGEST_INCLUDE_SYMBOLS`, `DIGEST_6H_ENABLED`, `DIGEST_6H_BUCKET_MIN`, `DIGEST_6H_MAX_BUCKETS` — periodic digest settings.
- `TELEGRAM_FORCE_IPV4` — force IPv4 network path inside Docker if IPv6 DNS breaks Telegram connectivity.

## Ops, Governance & Tooling
- `EVENTBUS_MAX_WORKERS` — size of the thread pool that executes synchronous EventBus subscribers.
- `OPS_API_TOKEN`, `OPS_API_ALLOWED_IPS` — authentication for the ops FastAPI surface.
- `CAPITAL_ALLOCATOR_ENABLED`, `CAPITAL_ALLOCATOR_INTERVAL_MIN` — govern per-strategy capital quotas.
- `EXECUTOR_ENABLED`, `EXECUTOR_STRATEGY`, `EXECUTOR_SIZE_MULT` — configure the optional ops executor loop.
- `PROMTAIL_ENABLED`, `PROMTAIL_ENDPOINT`, `PROMTAIL_JOURNAL_PATH` — ship logs to Loki.

Keep `.env.example` in sync by running `python scripts/generate_env_example.py` whenever defaults change. The CI check (`.github/workflows/env-consistency.yml`) fails if any code path references environment keys that are missing from the template.
