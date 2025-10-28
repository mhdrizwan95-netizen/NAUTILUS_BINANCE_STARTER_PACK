from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml


DEFAULT_CONFIG_PATH = Path("config/runtime.yaml")
_MAX_FUTURES_LEVERAGE = 125


@dataclass(frozen=True)
class BucketAllocations:
    futures_core: float = 0.60
    spot_margin: float = 0.25
    event: float = 0.10
    reserve: float = 0.05

    @property
    def total(self) -> float:
        return (
            self.futures_core
            + self.spot_margin
            + self.event
            + self.reserve
        )


@dataclass(frozen=True)
class PerStrategyRisk:
    per_trade_pct: Dict[str, float] = field(
        default_factory=lambda: {
            "trend": 0.02,
            "momentum": 0.02,
            "scalper": 0.01,
            "event": 0.005,
        }
    )
    max_concurrent: int = 5
    daily_stop_pct: float = 0.05


@dataclass(frozen=True)
class FuturesSettings:
    leverage: Dict[str, int] = field(
        default_factory=lambda: {
            "BTCUSDT": 5,
            "ETHUSDT": 5,
            "default": 3,
        }
    )
    desired_leverage: Dict[str, Optional[int]] = field(default_factory=dict)
    hedge_mode: bool = True


@dataclass(frozen=True)
class ExecutionSettings:
    slippage_bps_max: int = 15
    post_only_when_safe: bool = True
    client_id_prefix: str = "strategy"


@dataclass(frozen=True)
class SymbolUniverse:
    core: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT")


@dataclass(frozen=True)
class ScannerSettings:
    top_n: int = 30
    min_24h_vol_usdt: float = 5_000_000.0
    refresh_seconds: int = 300


@dataclass(frozen=True)
class BusSettings:
    max_queue: int = 1024
    signal_ttl_seconds: int = 120


@dataclass(frozen=True)
class UniverseFilterConfig:
    name: str
    venues: tuple[str, ...]
    min_24h_volume_usdt: float
    min_price_usdt: float
    max_price_usdt: Optional[float]
    min_futures_open_interest_usdt: Optional[float]
    min_leverage_supported: Optional[int]
    exclude_prefixes: tuple[str, ...]
    exclude_suffixes: tuple[str, ...]
    exclude_contains: tuple[str, ...]
    include_symbols: tuple[str, ...]
    min_30d_trend_pct: Optional[float]
    max_bid_ask_spread_pct: Optional[float]
    min_5m_atr_pct: Optional[float]
    min_price_change_pct_last_1h: Optional[float]
    min_liquidity_bid_size: Optional[float]
    min_orderbook_depth_usdt: Optional[float]
    min_tick_size_pct: Optional[float]
    new_listing_within_days: Optional[int]
    has_major_news_flag: bool
    max_concurrent_symbols: Optional[int]
    sort_by: Tuple[str, ...]
    max_symbols: Optional[int]

    @staticmethod
    def from_dict(name: str, payload: dict) -> "UniverseFilterConfig":
        venues = tuple(str(v).lower() for v in (payload.get("venues") or payload.get("exchange_type") or ["futures"]))
        sort_by_raw = payload.get("sort_by") or payload.get("rank_by") or ["24h_volume_usdt"]
        if isinstance(sort_by_raw, (list, tuple)):
            sort_by = tuple(str(item).lower() for item in sort_by_raw)
        else:
            sort_by = (str(sort_by_raw).lower(),)
        return UniverseFilterConfig(
            name=str(name),
            venues=venues,
            min_24h_volume_usdt=_as_float(payload.get("min_24h_volume_usdt"), 5_000_000.0),
            min_price_usdt=_as_float(payload.get("min_price_usdt"), _as_float(payload.get("min_price"), 0.01)),
            max_price_usdt=_as_float(payload.get("max_price_usdt"), _as_float(payload.get("max_price"), None)),
            min_futures_open_interest_usdt=_as_float(
                payload.get("min_futures_open_interest_usdt"),
                _as_float(payload.get("min_open_interest_usd"), None),
            ),
            min_leverage_supported=int(payload.get("min_leverage_supported"))
            if payload.get("min_leverage_supported") is not None
            else int(payload.get("allow_leverage_min"))
            if payload.get("allow_leverage_min") is not None
            else None,
            exclude_prefixes=tuple(str(x).upper() for x in (payload.get("exclude_prefixes") or [])),
            exclude_suffixes=tuple(str(x).upper() for x in (payload.get("exclude_suffixes") or [])),
            exclude_contains=tuple(str(x).upper() for x in (payload.get("exclude_contains") or [])),
            include_symbols=tuple(str(x).upper() for x in (payload.get("include_symbols") or [])),
            min_30d_trend_pct=_as_float(payload.get("min_30d_trend_pct"), None),
            max_bid_ask_spread_pct=_as_float(payload.get("max_bid_ask_spread_pct"), None),
            min_5m_atr_pct=_as_float(payload.get("min_5m_atr_pct"), None),
            min_price_change_pct_last_1h=_as_float(payload.get("min_price_change_pct_last_1h"), None),
            min_liquidity_bid_size=_as_float(payload.get("min_liquidity_bid_size"), None),
            min_orderbook_depth_usdt=_as_float(payload.get("min_orderbook_depth_usdt"), None),
            min_tick_size_pct=_as_float(payload.get("min_tick_size_pct"), None),
            new_listing_within_days=int(payload.get("new_listing_within_days")) if payload.get("new_listing_within_days") is not None else None,
            has_major_news_flag=bool(payload.get("has_major_news_flag", False)),
            max_concurrent_symbols=int(payload.get("max_concurrent_symbols")) if payload.get("max_concurrent_symbols") is not None else None,
            sort_by=sort_by,
            max_symbols=int(payload.get("max_symbols")) if payload.get("max_symbols") is not None else None,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    risk: PerStrategyRisk = field(default_factory=PerStrategyRisk)
    buckets: BucketAllocations = field(default_factory=BucketAllocations)
    futures: FuturesSettings = field(default_factory=FuturesSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    symbols: SymbolUniverse = field(default_factory=SymbolUniverse)
    scanner: ScannerSettings = field(default_factory=ScannerSettings)
    bus: BusSettings = field(default_factory=BusSettings)
    universes: Dict[str, "UniverseFilterConfig"] = field(default_factory=dict)
    snapshot_dir: Optional[str] = None
    demo_mode: bool = False  # Generates sample signals when true


def _as_float(value: Optional[float], default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper()


def _parse_leverage_overrides(raw: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    overrides: Dict[str, Optional[int]] = {}
    if not raw:
        return overrides
    for symbol, value in raw.items():
        sym = _normalize_symbol(symbol)
        if isinstance(value, str) and value.strip().lower() == "default":
            overrides[sym] = None
            continue
        if value is None:
            overrides[sym] = None
            continue
        try:
            leverage_int = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Invalid leverage value for {sym}: {value!r}") from exc
        if leverage_int < 1 or leverage_int > _MAX_FUTURES_LEVERAGE:
            raise ValueError(
                f"Leverage for {sym} must be between 1 and {_MAX_FUTURES_LEVERAGE}, got {leverage_int}"
            )
        overrides[sym] = leverage_int
    return overrides


def _ensure_path(path_like: str | os.PathLike[str] | None) -> Path:
    if not path_like:
        return DEFAULT_CONFIG_PATH
    return Path(path_like)


def load_runtime_config(path: str | os.PathLike[str] | None = None) -> RuntimeConfig:
    """
    Load runtime orchestration configuration from YAML.
    Environment variable override: ``RUNTIME_CONFIG_PATH``.
    """
    env_path = os.getenv("RUNTIME_CONFIG_PATH")
    cfg_path = _ensure_path(path or env_path or DEFAULT_CONFIG_PATH)
    if not cfg_path.exists():
        return RuntimeConfig()

    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    risk_section = data.get("risk", {}) or {}
    per_trade_pct = risk_section.get("per_trade_pct") or {}
    risk = PerStrategyRisk(
        per_trade_pct={k.lower(): float(v) for k, v in per_trade_pct.items()},
        max_concurrent=int(risk_section.get("max_concurrent", 5)),
        daily_stop_pct=_as_float(risk_section.get("daily_stop_pct"), 0.05),
    )

    buckets_section = data.get("buckets", {}) or {}
    buckets = BucketAllocations(
        futures_core=_as_float(buckets_section.get("futures_core"), 0.60),
        spot_margin=_as_float(buckets_section.get("spot_margin"), 0.25),
        event=_as_float(buckets_section.get("event"), 0.10),
        reserve=_as_float(buckets_section.get("reserve"), 0.05),
    )

    futures_section = data.get("futures", {}) or {}
    futures = FuturesSettings(
        leverage={
            str(k).upper(): int(v)
            for k, v in (futures_section.get("leverage") or {}).items()
        }
        or {"BTCUSDT": 5, "ETHUSDT": 5, "default": 3},
        desired_leverage=_parse_leverage_overrides(futures_section.get("futures_leverage")),
        hedge_mode=bool(futures_section.get("hedge_mode", True)),
    )

    execution_section = data.get("execution", {}) or {}
    execution = ExecutionSettings(
        slippage_bps_max=int(execution_section.get("slippage_bps_max", 15)),
        post_only_when_safe=bool(execution_section.get("post_only_when_safe", True)),
        client_id_prefix=str(execution_section.get("client_id_prefix", "strategy")),
    )

    symbols_section = data.get("symbols", {}) or {}
    symbols = SymbolUniverse(
        core=tuple(str(s).upper() for s in (symbols_section.get("core") or []))
        or ("BTCUSDT", "ETHUSDT", "BNBUSDT"),
    )

    scanner_section = data.get("scanner", {}) or {}
    scanner = ScannerSettings(
        top_n=int(scanner_section.get("top_n", 30)),
        min_24h_vol_usdt=_as_float(scanner_section.get("min_24h_vol_usdt"), 5_000_000.0),
        refresh_seconds=int(scanner_section.get("refresh_seconds", 300)),
    )

    universes_section = data.get("universes", {}) or {}
    universes = {
        str(name).lower(): UniverseFilterConfig.from_dict(name, cfg or {})
        for name, cfg in universes_section.items()
    }

    bus_section = data.get("bus", {}) or {}
    bus = BusSettings(
        max_queue=int(bus_section.get("max_queue", 1024)),
        signal_ttl_seconds=int(bus_section.get("signal_ttl_seconds", 120)),
    )

    demo_mode = bool(data.get("demo_mode", False))
    snapshot_dir = data.get("snapshot_dir")
    if snapshot_dir is not None:
        snapshot_dir = str(snapshot_dir)

    return RuntimeConfig(
        risk=risk,
        buckets=buckets,
        futures=futures,
        execution=execution,
        symbols=symbols,
        scanner=scanner,
        bus=bus,
        universes=universes,
        demo_mode=demo_mode,
        snapshot_dir=snapshot_dir,
    )
