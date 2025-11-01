from __future__ import annotations

"""
Configuration loader for the DEX sniper stack.

Environment knobs mirror the playbook defaults while staying optional so the
entire module can be exercised in tests without touching real wallets.
"""

from dataclasses import dataclass
import os


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class DexConfig:
    feed_enabled: bool
    exec_enabled: bool
    watcher_enabled: bool
    max_live_positions: int
    size_tier_a: float
    size_tier_b: float
    stop_loss_pct: float
    tp1_pct: float
    tp1_portion: float
    tp2_pct: float
    tp2_portion: float
    trail_pct: float
    slippage_bps: float
    max_slippage_bps: float
    tax_max_pct: float
    min_liq_usd: float
    max_top10_pct: float
    state_path: str
    chain_whitelist: tuple[str, ...]
    rpc_url: str
    chain_id: int
    router_address: str
    stable_token: str
    wrapped_native_token: str
    wallet_private_key: str
    max_gas_price_wei: int
    gas_limit: int
    price_oracle: str
    watcher_poll_sec: float

    @property
    def tp_targets(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Return ladder targets as ((pct, portion), ...)."""
        return ((self.tp1_pct, self.tp1_portion), (self.tp2_pct, self.tp2_portion))


def load_dex_config() -> DexConfig:
    """Load configuration from environment with safe defaults."""
    state_path = os.getenv("DEX_STATE_PATH", "state/dex_positions.json")
    chains = os.getenv("DEX_CHAIN_WHITELIST", "ETH,BSC,BASE")
    whitelist = tuple(
        sorted({c.strip().upper() for c in chains.split(",") if c.strip()})
    )
    rpc_url = os.getenv("DEX_RPC_URL", "").strip()
    router_address = os.getenv("DEX_ROUTER_ADDRESS", "").strip()
    stable_token = os.getenv("DEX_STABLE_TOKEN", "").strip()
    wrapped_native = os.getenv("DEX_WRAPPED_NATIVE", "").strip()
    private_key = os.getenv("DEX_PRIVATE_KEY", "").strip()
    return DexConfig(
        feed_enabled=_as_bool(os.getenv("DEX_FEED_ENABLED"), False),
        exec_enabled=_as_bool(os.getenv("DEX_EXEC_ENABLED"), False),
        watcher_enabled=_as_bool(os.getenv("DEX_WATCHER_ENABLED"), True),
        max_live_positions=max(1, _as_int(os.getenv("DEX_MAX_LIVE"), 1)),
        size_tier_a=_as_float(os.getenv("DEX_SIZE_TIER_A"), 50.0),
        size_tier_b=_as_float(os.getenv("DEX_SIZE_TIER_B"), 25.0),
        stop_loss_pct=_as_float(os.getenv("DEX_STOP_LOSS_PCT"), 0.12),
        tp1_pct=_as_float(os.getenv("DEX_TP1_PCT"), 0.20),
        tp1_portion=_as_float(os.getenv("DEX_TP1_PORTION"), 0.40),
        tp2_pct=_as_float(os.getenv("DEX_TP2_PCT"), 0.40),
        tp2_portion=_as_float(os.getenv("DEX_TP2_PORTION"), 0.30),
        trail_pct=_as_float(os.getenv("DEX_TRAIL_PCT"), 0.10),
        slippage_bps=_as_float(os.getenv("DEX_SLIPPAGE_BPS"), 80.0),
        max_slippage_bps=_as_float(os.getenv("DEX_MAX_SLIPPAGE_BPS"), 120.0),
        tax_max_pct=_as_float(os.getenv("DEX_TAX_MAX_PCT"), 5.0),
        min_liq_usd=_as_float(os.getenv("DEX_MIN_LIQ_USD"), 200_000.0),
        max_top10_pct=_as_float(os.getenv("DEX_TOP10_MAX_PCT"), 70.0),
        state_path=state_path,
        chain_whitelist=whitelist,
        rpc_url=rpc_url,
        chain_id=_as_int(os.getenv("DEX_CHAIN_ID"), 56),
        router_address=router_address,
        stable_token=stable_token,
        wrapped_native_token=wrapped_native,
        wallet_private_key=private_key,
        max_gas_price_wei=int(_as_float(os.getenv("DEX_MAX_GAS_WEI"), 50_000_000_000)),
        gas_limit=int(_as_float(os.getenv("DEX_GAS_LIMIT"), 400_000)),
        price_oracle=os.getenv("DEX_PRICE_ORACLE", "dexscreener"),
        watcher_poll_sec=_as_float(os.getenv("DEX_WATCHER_POLL_SEC"), 5.0),
    )
