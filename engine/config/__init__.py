from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from engine.config.defaults import GLOBAL_DEFAULTS, RISK_DEFAULTS
from engine.config.env import env_bool, env_float, env_int, env_str, split_symbols


class Settings:
    """Runtime configuration for the engine service."""

    def __init__(self) -> None:
        venue = os.getenv("VENUE", "BINANCE").upper()
        self.venue = venue

        # Initialize defaults for attributes that are populated conditionally.
        self.spot_base = ""
        self.futures_base = ""
        self.api_key = ""
        self.api_secret = ""
        self.base_url = ""
        self.mode = ""
        self.is_futures = False
        self.options_base = ""
        self.options_enabled = False

        if venue == "IBKR":
            # IBKR-specific configuration
            self.mode = "ibkr"
            self.is_futures = False  # IBKR doesn't use futures concept like Binance
            self.api_key = os.getenv("IBKR_USERNAME", "")
            self.api_secret = os.getenv("IBKR_PASSWORD", "")
            host = os.getenv("IBKR_HOST", "127.0.0.1")
            port = os.getenv("IBKR_PORT", "7497")
            self.base_url = f"{host}:{port}"
        elif venue == "KRAKEN":
            # Kraken Futures configuration
            self.mode = os.getenv("KRAKEN_MODE", "testnet").lower()
            self.is_futures = True
            self.base_url = os.getenv("KRAKEN_BASE_URL", "https://demo-futures.kraken.com").rstrip(
                "/"
            )
            # Kraken API credentials (secret provided base64 encoded per Kraken docs)
            self.api_key = os.getenv("KRAKEN_API_KEY", "")
            self.api_secret = os.getenv("KRAKEN_API_SECRET", "")
            # Optional websocket endpoints
            self.ws_url = os.getenv(
                "KRAKEN_WS_URL",
                "wss://demo-futures.kraken.com/ws/v1",
            )
            # Compatibility aliases so downstream code can reuse attr names
            self.spot_base = self.base_url
            self.futures_base = self.base_url
        else:
            # Binance-specific configuration
            mode = os.getenv("BINANCE_MODE", "demo").lower()
            self.mode = mode
            futures_tokens = ("futures", "usdm", "coinm", "perp")
            self.is_futures = any(token in mode for token in futures_tokens)

            demo_indicators = ("demo", "test", "paper")
            is_demo_like = any(token in mode for token in demo_indicators)

            spot_base_default = "https://testnet.binance.vision"
            futures_demo_default = "https://testnet.binancefuture.com"
            futures_live_default = "https://fapi.binance.com"

            self.spot_base = os.getenv(
                "BINANCE_SPOT_BASE", os.getenv("DEMO_SPOT_BASE", spot_base_default)
            )
            futures_live_base = os.getenv("BINANCE_USDM_BASE") or os.getenv(
                "BINANCE_FUTURES_BASE", futures_live_default
            )
            futures_demo_base = os.getenv("DEMO_USDM_BASE", futures_demo_default)

            # Prefer explicit demo/testnet credentials if provided
            demo_key = os.getenv("DEMO_API_KEY") or os.getenv("DEMO_API_KEY_SPOT")
            demo_secret = os.getenv("DEMO_API_SECRET") or os.getenv("DEMO_API_SECRET_SPOT")

            live_key = os.getenv("BINANCE_API_KEY", "")
            live_secret = os.getenv("BINANCE_API_SECRET", "")

            if self.is_futures:
                base_choice = futures_demo_base if is_demo_like else futures_live_base
                self.api_key = demo_key or live_key if is_demo_like else live_key
                self.api_secret = demo_secret or live_secret if is_demo_like else live_secret
                self.futures_base = base_choice
                self.base_url = base_choice
            else:
                self.futures_base = futures_live_base
                if is_demo_like:
                    self.api_key = demo_key or live_key
                    self.api_secret = demo_secret or live_secret
                    self.base_url = self.spot_base
                else:
                    self.api_key = live_key
                    self.api_secret = live_secret
                    self.base_url = os.getenv("BINANCE_SPOT_BASE", "https://api.binance.com")

            self.options_base = os.getenv(
                "BINANCE_OPTIONS_BASE", "https://vapi.binance.com"
            ).rstrip("/")
            self.options_enabled = _as_bool(os.getenv("BINANCE_OPTIONS_ENABLED"), False)

            # Only require credentials for Binance venue
            if not self.api_key or not self.api_secret:
                # Allow missing credentials in test/demo environments; callers should
                # ensure TRADING_ENABLED is false when running without real keys.
                self.api_key = self.api_key or ""
                self.api_secret = self.api_secret or ""

            # Validate futures base URL if in futures mode
            if self.is_futures and not self.futures_base:
                raise RuntimeError(
                    f"BINANCE_FUTURES_BASE must be set for futures mode, got: {self.futures_base}"
                )

        if venue == "KRAKEN":
            self.recv_window = 0
            self.timeout = float(
                os.getenv("KRAKEN_API_TIMEOUT", os.getenv("BINANCE_API_TIMEOUT", "10"))
            )
        else:
            self.recv_window = int(os.getenv("BINANCE_RECV_WINDOW", "5000"))
            self.timeout = float(os.getenv("BINANCE_API_TIMEOUT", "10"))
        self.trading_enabled = os.getenv("TRADING_ENABLED", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        default_symbols = "BTCUSDT.BINANCE"
        if venue == "KRAKEN":
            default_symbols = "PI_XBTUSD.KRAKEN,PI_ETHUSD.KRAKEN"
        trade_symbols_raw = env_str(
            "TRADE_SYMBOLS", GLOBAL_DEFAULTS.get("TRADE_SYMBOLS", default_symbols)
        )
        normalized = trade_symbols_raw.strip().lower()
        if not trade_symbols_raw.strip():
            self.allowed_symbols = _split_symbols(default_symbols)
        elif normalized in {"*", "all"}:
            self.allowed_symbols = []
        else:
            self.allowed_symbols = _split_symbols(trade_symbols_raw)
        self.min_notional = float(os.getenv("MIN_NOTIONAL_USDT", "10"))
        self.max_notional = float(os.getenv("MAX_NOTIONAL_USDT", "10000"))

    @property
    def api_base(self):
        """Dynamically select appropriate base URL based on mode."""
        return self.base_url


def _split_symbols(value: str) -> list[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or ["BTCUSDT.BINANCE"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _as_bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "y", "on"}


def _as_float(v: str | None, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default


def _as_int(v: str | None, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


def _as_list(v: str | None) -> List[str]:
    if not v:
        return []
    return [s.strip() for s in v.split(",") if s.strip()]


@dataclass(frozen=True)
class RiskConfig:
    trading_enabled: bool
    min_notional_usdt: float
    max_notional_usdt: float
    max_orders_per_min: int
    trade_symbols: List[str] | None
    dust_threshold_usd: float
    # breakers
    exposure_cap_symbol_usd: float
    exposure_cap_total_usd: float
    venue_error_breaker_pct: float
    venue_error_window_sec: int
    exposure_cap_venue_usd: float
    equity_floor_usd: float
    equity_drawdown_limit_pct: float
    equity_cooldown_sec: int
    margin_enabled: bool
    margin_min_level: float
    margin_max_liability_usd: float
    margin_max_leverage: float
    options_enabled: bool


DEFAULT_TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


def load_risk_config() -> RiskConfig:
    settings = get_settings()

    trade_symbols_env_raw = os.getenv("TRADE_SYMBOLS")
    if trade_symbols_env_raw is None:
        trade_symbols = DEFAULT_TRADE_SYMBOLS.copy()
    else:
        trade_symbols_env = trade_symbols_env_raw.strip()
        if not trade_symbols_env:
            trade_symbols = DEFAULT_TRADE_SYMBOLS.copy()
        elif trade_symbols_env.lower() in {"*", "all"}:
            trade_symbols = []
        else:
            parsed = split_symbols(trade_symbols_env) or []
            trade_symbols = parsed or DEFAULT_TRADE_SYMBOLS.copy()

    trading_enabled_env = os.getenv("TRADING_ENABLED")
    if trading_enabled_env is None:
        trading_enabled = not env_bool("DRY_RUN", GLOBAL_DEFAULTS["DRY_RUN"])
    else:
        trading_enabled = env_bool("TRADING_ENABLED", RISK_DEFAULTS["TRADING_ENABLED"])
    # Futures venues typically have higher min notional (e.g., 100 USDT on testnet).
    # If MIN_NOTIONAL_USDT not explicitly set, choose a sensible per-mode default.
    default_min_notional = 100.0 if getattr(settings, "is_futures", False) else 5.0
    return RiskConfig(
        trading_enabled=trading_enabled,
        min_notional_usdt=env_float("MIN_NOTIONAL_USDT", default_min_notional),
        max_notional_usdt=env_float("MAX_NOTIONAL_USDT", RISK_DEFAULTS["MAX_NOTIONAL_USDT"]),
        max_orders_per_min=env_int("MAX_ORDERS_PER_MIN", RISK_DEFAULTS["MAX_ORDERS_PER_MIN"]),
        trade_symbols=trade_symbols,
        dust_threshold_usd=env_float("DUST_THRESHOLD_USD", RISK_DEFAULTS["DUST_THRESHOLD_USD"]),
        exposure_cap_symbol_usd=env_float(
            "EXPOSURE_CAP_SYMBOL_USD", RISK_DEFAULTS["EXPOSURE_CAP_SYMBOL_USD"]
        ),
        exposure_cap_total_usd=env_float(
            "EXPOSURE_CAP_TOTAL_USD", RISK_DEFAULTS["EXPOSURE_CAP_TOTAL_USD"]
        ),
        venue_error_breaker_pct=env_float(
            "VENUE_ERROR_BREAKER_PCT", RISK_DEFAULTS["VENUE_ERROR_BREAKER_PCT"]
        ),
        venue_error_window_sec=env_int(
            "VENUE_ERROR_WINDOW_SEC", RISK_DEFAULTS["VENUE_ERROR_WINDOW_SEC"]
        ),
        exposure_cap_venue_usd=env_float(
            "EXPOSURE_CAP_VENUE_USD", RISK_DEFAULTS["EXPOSURE_CAP_VENUE_USD"]
        ),
        equity_floor_usd=env_float("EQUITY_FLOOR_USD", RISK_DEFAULTS["EQUITY_FLOOR_USD"]),
        equity_drawdown_limit_pct=env_float(
            "EQUITY_DRAWDOWN_LIMIT_PCT", RISK_DEFAULTS["EQUITY_DRAWDOWN_LIMIT_PCT"]
        ),
        equity_cooldown_sec=env_int("EQUITY_COOLDOWN_SEC", RISK_DEFAULTS["EQUITY_COOLDOWN_SEC"]),
        margin_enabled=env_bool(
            "MARGIN_ENABLED",
            env_bool("BINANCE_MARGIN_ENABLED", RISK_DEFAULTS["MARGIN_ENABLED"]),
        ),
        margin_min_level=env_float("MARGIN_MIN_LEVEL", RISK_DEFAULTS["MARGIN_MIN_LEVEL"]),
        margin_max_liability_usd=env_float(
            "MARGIN_MAX_LIABILITY_USD", RISK_DEFAULTS["MARGIN_MAX_LIABILITY_USD"]
        ),
        margin_max_leverage=env_float("MARGIN_MAX_LEVERAGE", RISK_DEFAULTS["MARGIN_MAX_LEVERAGE"]),
        options_enabled=env_bool(
            "OPTIONS_ENABLED",
            env_bool("BINANCE_OPTIONS_ENABLED", RISK_DEFAULTS["OPTIONS_ENABLED"]),
        ),
    )


# ---- Quote currency + universe helpers ----
QUOTE_CCY = os.getenv("QUOTE_CCY", "USDT").upper()


def norm_symbol(sym: str) -> str:
    """Ensure symbols are in BASEQUOTE (e.g., BTCUSDT) without venue suffix."""
    s = sym.split(".")[0].upper()
    if s.endswith(QUOTE_CCY) or s.endswith("USD"):
        return s
    return f"{s}{QUOTE_CCY}"


async def list_all_testnet_pairs() -> List[str]:
    """Fetch all tradeable spot pairs from Binance testnet."""
    try:
        import httpx  # type: ignore
    except ModuleNotFoundError:
        # httpx is an optional dependency; fall back to a static list when it is
        # unavailable (e.g., in light-weight tooling environments).
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

    base_url = "https://testnet.binance.vision"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{base_url}/api/v3/exchangeInfo")
            r.raise_for_status()
            data = r.json()
            symbols = []
            for symbol_info in data.get("symbols", []):
                status = symbol_info.get("status", "")
                if status == "TRADING":
                    symbol = symbol_info.get("symbol", "")
                    if symbol and symbol.endswith("USDT"):
                        symbols.append(symbol)
            return sorted(symbols)
        except Exception:
            # Fallback to a few hardcoded pairs
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


@dataclass(frozen=True)
class VenueFeeConfig:
    taker_bps: float


def load_fee_config(venue: str) -> VenueFeeConfig:
    return VenueFeeConfig(taker_bps=_as_float(os.getenv(f"{venue}_TAKER_BPS"), 10.0))


@dataclass(frozen=True)
class IbkrFeeConfig:
    mode: str  # "per_share" or "bps"
    per_share_usd: float
    min_trade_fee_usd: float
    bps: float


def load_ibkr_fee_config() -> IbkrFeeConfig:
    mode = os.getenv("IBKR_FEE_MODE", "per_share").lower()
    return IbkrFeeConfig(
        mode=mode,
        per_share_usd=_as_float(os.getenv("IBKR_FEE_PER_SHARE"), 0.005),
        min_trade_fee_usd=_as_float(os.getenv("IBKR_MIN_TRADE_FEE_USD"), 1.0),
        bps=_as_float(os.getenv("IBKR_FEE_BPS"), 1.0),  # only used if mode == "bps"
    )


def ibkr_min_notional_usd() -> float:
    return _as_float(os.getenv("IBKR_MIN_NOTIONAL_USD"), 5.0)


@dataclass(frozen=True)
class StrategyConfig:
    enabled: bool
    dry_run: bool
    symbols: List[str]
    interval_sec: int
    fast: int
    slow: int
    quote_usdt: float
    default_market: str
    # HMM policy knobs
    hmm_enabled: bool
    hmm_model_path: str
    hmm_window: int
    hmm_slippage_bps: float
    cooldown_sec: int
    tp_bps: float
    sl_bps: float
    # --- Ensemble ---
    ensemble_enabled: bool
    ensemble_min_conf: float
    ensemble_weights: dict[str, float]


def load_strategy_config() -> StrategyConfig:
    # Defaults: safe and conservative
    symbols_env = os.getenv("STRATEGY_SYMBOLS")
    if symbols_env:
        logging.getLogger(__name__).warning(
            "STRATEGY_SYMBOLS is deprecated; use TRADE_SYMBOLS or per-strategy overrides."
        )
        symbols = _as_list(symbols_env)
    else:
        trade_symbols_raw = env_str("TRADE_SYMBOLS", GLOBAL_DEFAULTS["TRADE_SYMBOLS"])
        if trade_symbols_raw.strip().lower() in {"*", "all", ""}:
            symbols = []
        else:
            symbols = _as_list(trade_symbols_raw)
    try:
        settings = get_settings()
        default_market = os.getenv("STRATEGY_DEFAULT_MARKET") or (
            "futures" if getattr(settings, "is_futures", False) else "spot"
        )
    except Exception:
        default_market = os.getenv("STRATEGY_DEFAULT_MARKET", "spot")
    return StrategyConfig(
        enabled=_as_bool(os.getenv("STRATEGY_ENABLED"), False),
        dry_run=_as_bool(os.getenv("STRATEGY_DRY_RUN"), True),
        symbols=symbols,
        interval_sec=_as_int(os.getenv("STRATEGY_INTERVAL_SEC"), 60),
        fast=_as_int(os.getenv("STRATEGY_FAST"), 9),
        slow=_as_int(os.getenv("STRATEGY_SLOW"), 21),
        quote_usdt=_as_float(os.getenv("STRATEGY_QUOTE_USDT"), 10.0),
        default_market=default_market.lower(),
        hmm_enabled=_as_bool(os.getenv("HMM_ENABLED"), False),
        hmm_model_path=os.getenv("HMM_MODEL_PATH", "engine/models/hmm_policy.pkl"),
        hmm_window=_as_int(os.getenv("HMM_WINDOW"), 120),
        hmm_slippage_bps=_as_float(os.getenv("HMM_SLIPPAGE_BPS"), 3.0),
        cooldown_sec=_as_int(os.getenv("COOLDOWN_SEC"), 30),
        tp_bps=_as_float(os.getenv("TP_BPS"), 20.0),
        sl_bps=_as_float(os.getenv("SL_BPS"), 30.0),
        # --- Ensemble ---
        ensemble_enabled=_as_bool(os.getenv("ENSEMBLE_ENABLED"), False),
        ensemble_min_conf=_as_float(os.getenv("ENSEMBLE_MIN_CONF"), 0.6),
        ensemble_weights={
            k: float(v)
            for k, v in [
                w.split(":")
                for w in os.getenv("ENSEMBLE_WEIGHTS", "hmm_v1:0.5,ma_v1:0.5").split(",")
            ]
        },
    )
