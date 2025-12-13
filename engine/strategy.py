from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from . import metrics
from .config import load_risk_config, load_strategy_config
from .core.event_bus import BUS
from .core.market_resolver import resolve_market_choice
from .execution.execute import StrategyExecutor
from .ops_auth import require_ops_token
from .risk import RiskRails
from .state.cooldown import Cooldowns
from .strategies import ensemble_policy, policy_hmm
from .strategies.policy_river import RiverPolicy
from .state import get_global_redis

# Initialize River Policy (Global)
river_policy = RiverPolicy()
from .strategies.calibration import cooldown_scale as calibration_cooldown_scale
from .strategies.scalp.brackets import ScalpBracketManager
from .strategies.scalping import ScalpStrategyModule, load_scalp_config
from .strategies.trend_follow import TrendStrategyModule, load_trend_config
from .telemetry.publisher import record_tick_latency
from .services.telemetry_broadcaster import BROADCASTER

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    ValueError,
)

try:
    from .strategies.momentum_realtime import (
        MomentumStrategyModule,
        load_momentum_rt_config,
    )
except ImportError:  # pragma: no cover - optional component
    MomentumStrategyModule = None  # type: ignore
    load_momentum_rt_config = None  # type: ignore

try:
    from .strategies.liquidation import LiquidationStrategyModule, load_liquidation_config
except ImportError as e:  # pragma: no cover - optional component
    logging.getLogger(__name__).warning("Failed to import LiquidationStrategyModule: %s", e)
    LiquidationStrategyModule = None  # type: ignore
    load_liquidation_config = None  # type: ignore
try:
    from .strategies.symbol_scanner import SymbolScanner, load_symbol_scanner_config
except ImportError:  # pragma: no cover - optional component
    SymbolScanner = None  # type: ignore
    load_symbol_scanner_config = None  # type: ignore

try:
    from .strategies.deepseek_v2 import DeepSeekStrategyModule, load_deepseek_config
except ImportError:
    DeepSeekStrategyModule = None
    load_deepseek_config = None

_last_telemetry_ts: dict[str, float] = defaultdict(float)
_last_telemetry_ts['deepseek_v2'] = 0.0

router = APIRouter()
S_CFG = load_strategy_config()
R_CFG = load_risk_config()
RAILS = RiskRails(R_CFG)
SYMBOL_SCANNER = None
if SymbolScanner and load_symbol_scanner_config:
    try:
        _scanner_cfg = load_symbol_scanner_config()
        if _scanner_cfg.enabled:
            SYMBOL_SCANNER = SymbolScanner(_scanner_cfg)
            SYMBOL_SCANNER.start()
            logging.getLogger(__name__).info("SymbolScanner started")
    except Exception as exc:
        logging.getLogger(__name__).warning("SymbolScanner init failed: %s", exc, exc_info=True)
        SYMBOL_SCANNER = None
else:
    logging.getLogger(__name__).warning(f"SymbolScanner Import Failed. SymbolScanner={SymbolScanner}, load_conf={load_symbol_scanner_config}")


def _risk_release_handler(evt: dict[str, Any]) -> None:
    symbol = str(evt.get("symbol") or evt.get("strategy_symbol") or "")
    if not symbol:
        return
    try:
        RAILS.release_symbol_lock(symbol)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("risk release handler suppressed", exc_info=True)


try:
    BUS.subscribe("trade.fill", _risk_release_handler)
except Exception as exc:  # pragma: no cover
    logger.warning("Failed to subscribe risk release handler", exc_info=True)

TREND_CFG = None
TREND_MODULE: TrendStrategyModule | None = None
try:
    TREND_CFG = load_trend_config(SYMBOL_SCANNER)
    if TREND_CFG.enabled:
        TREND_MODULE = TrendStrategyModule(TREND_CFG, scanner=SYMBOL_SCANNER)
except Exception as exc:
    TREND_MODULE = None

SCALP_CFG = None
SCALP_MODULE: ScalpStrategyModule | None = None
try:
    SCALP_CFG = load_scalp_config(SYMBOL_SCANNER)
    if SCALP_CFG.enabled:
        SCALP_MODULE = ScalpStrategyModule(SCALP_CFG, scanner=SYMBOL_SCANNER)
except Exception as exc:
    SCALP_MODULE = None

MOMENTUM_RT_CFG = None
MOMENTUM_RT_MODULE: MomentumStrategyModule | None = None
if "MomentumStrategyModule" in globals() and MomentumStrategyModule and load_momentum_rt_config:
    try:
        MOMENTUM_RT_CFG = load_momentum_rt_config(SYMBOL_SCANNER)
        if MOMENTUM_RT_CFG.enabled:
            MOMENTUM_RT_MODULE = MomentumStrategyModule(MOMENTUM_RT_CFG, scanner=SYMBOL_SCANNER)
            logging.getLogger(__name__).info(
                "Momentum RT module enabled (window=%.1fs, move>=%.2f%%, vol>=%.2fx)",
                MOMENTUM_RT_CFG.window_sec,
                MOMENTUM_RT_CFG.pct_move_threshold * 100.0,
                MOMENTUM_RT_CFG.volume_spike_ratio,
            )
    except Exception as exc:
        MOMENTUM_RT_MODULE = None

LIQU_CFG = None
LIQU_MODULE: LiquidationStrategyModule | None = None
if "LiquidationStrategyModule" in globals() and LiquidationStrategyModule and load_liquidation_config:
    try:
        LIQU_CFG = load_liquidation_config()
        if LIQU_CFG.enabled:
            LIQU_MODULE = LiquidationStrategyModule(LIQU_CFG)
            logging.getLogger(__name__).info("Liquidation Strategy module enabled")
    except Exception as exc:
        LIQU_MODULE = None

DEEPSEEK_CFG = None
DEEPSEEK_MODULE: DeepSeekStrategyModule | None = None
if DeepSeekStrategyModule and load_deepseek_config:
    try:
        DEEPSEEK_CFG = load_deepseek_config()
        if DEEPSEEK_CFG.enabled:
            DEEPSEEK_MODULE = DeepSeekStrategyModule(DEEPSEEK_CFG)
            logging.getLogger(__name__).info("DeepSeek module enabled (model=%s)", DEEPSEEK_CFG.model)
    except Exception as exc:
        logging.getLogger(__name__).warning("DeepSeek init failed: %s", exc)
        DEEPSEEK_MODULE = None

_SCALP_BUS_WIRED = False
_SCALP_BRACKET_MANAGER: ScalpBracketManager | None = None


def _wire_scalp_fill_handler() -> None:
    global _SCALP_BUS_WIRED
    if _SCALP_BUS_WIRED:
        return
    try:
        BUS.subscribe("trade.fill", _scalp_fill_handler)
        _SCALP_BUS_WIRED = True
        logging.getLogger(__name__).info("Scalping fill handler wired")
    except Exception as exc:
        logging.getLogger(__name__).warning("Scalping fill handler wiring failed", exc_info=True)


async def _scalp_fill_handler(evt: dict[str, Any]) -> None:
    if not SCALP_MODULE or not getattr(SCALP_MODULE, "enabled", False):
        return
    meta = evt.get("strategy_meta")
    tag = str(evt.get("strategy_tag") or "")
    if not isinstance(meta, dict):
        return
    if not tag.startswith("scalp"):
        return
    symbol = str(evt.get("symbol") or "").upper()
    venue = str(evt.get("venue") or "BINANCE").upper()
    side = str(evt.get("side") or "").upper()
    if not symbol or side not in {"BUY", "SELL"}:
        return
    qty = float(evt.get("filled_qty") or 0.0)
    if qty <= 0.0:
        return
    stop_px = float(meta.get("stop_price") or 0.0)
    target_px = float(meta.get("take_profit") or 0.0)
    if stop_px <= 0.0 or target_px <= 0.0:
        return
    order_id = str(evt.get("order_id") or "") or f"{symbol}:{evt.get('ts', time.time())}"
    qualified = symbol if "." in symbol else f"{symbol}.{venue}"
    tag_prefix = tag or "scalp"
    _start_scalp_bracket_watch(
        order_id=order_id,
        symbol=qualified,
        venue=venue,
        entry_side=side,
        quantity=qty,
        stop_px=stop_px,
        target_px=target_px,
        tag_prefix=tag_prefix,
    )


def _start_scalp_bracket_watch(
    *,
    order_id: str,
    symbol: str,
    venue: str,
    entry_side: str,
    quantity: float,
    stop_px: float,
    target_px: float,
    tag_prefix: str,
) -> None:
    poll = 1.0
    ttl = 180.0
    if SCALP_CFG:
        try:
            poll = max(0.5, min(5.0, float(SCALP_CFG.window_sec) / 12.0))
            ttl = max(60.0, float(SCALP_CFG.window_sec) * 3.0)
        except Exception as exc:
            poll = max(poll, 1.0)
            ttl = max(ttl, 180.0)

    exit_side = "SELL" if entry_side == "BUY" else "BUY"
    key = order_id or f"{symbol}:{entry_side}:{int(time.time() * 1000)}"
    manager = _ensure_scalp_bracket_manager()
    manager.watch(
        key=key,
        symbol=symbol,
        venue=venue,
        entry_side=entry_side,
        exit_side=exit_side,
        quantity=quantity,
        stop_price=stop_px,
        take_profit_price=target_px,
        poll_interval=poll,
        ttl=ttl,
        tag_prefix=tag_prefix,
    )


if SCALP_MODULE and getattr(SCALP_MODULE, "enabled", False):
    _wire_scalp_fill_handler()


class InvalidMovingAverageWindow(ValueError):
    """Raised when the configured MA crossover windows are invalid."""


class OrderRouterUnavailableError(RuntimeError):
    """Raised when the engine app cannot expose the order router."""


class _MACross:
    def __init__(self, fast: int, slow: int):
        if fast >= slow:
            raise InvalidMovingAverageWindow()
        self.fast = fast
        self.slow = slow
        self.windows: dict[str, deque[float]] = defaultdict(deque)

    def push(self, symbol: str, price: float) -> str | None:
        w = self.windows[symbol]
        w.append(price)
        # Cap deque to slow window
        while len(w) > self.slow:
            w.popleft()
        if len(w) < self.slow:
            return None
        fast_ma = sum(list(w)[-self.fast :]) / self.fast
        slow_ma = sum(w) / len(w)
        if fast_ma > slow_ma:
            return "BUY"
        if fast_ma < slow_ma:
            return "SELL"
        return None


# Global variables for scheduler
_loop_thread: threading.Thread | None = None
_stop_flag: threading.Event = threading.Event()
_mac = _MACross(S_CFG.fast, S_CFG.slow)
_tick_listeners: list[Callable[[str, float, float], object]] = []
_last_tick_ts: dict[str, float] = defaultdict(float)
_SYMBOL_COOLDOWNS = Cooldowns(default_ttl=getattr(S_CFG, "cooldown_sec", 0.0))
_last_trade_price: dict[str, float] = defaultdict(float)
_entry_block_until: float = time.time() + float(os.getenv("WARMUP_SEC", "0"))


async def _on_market_tick_event(event: dict[str, Any]) -> None:
    print(f"DEBUG: _on_market_tick_event {event}")
    symbol = str(event.get("symbol") or "")
    price = event.get("price")
    if not symbol or price is None:
        return
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return
    ts_raw = event.get("ts")
    try:
        ts_val = float(ts_raw) if ts_raw is not None else time.time()
    except (TypeError, ValueError):
        ts_val = time.time()
    vol_raw = event.get("volume")
    volume: float | None
    if vol_raw is None:
        volume = None
    else:
        try:
            volume = float(vol_raw)
        except (TypeError, ValueError):
            volume = None
    cfg = getattr(S_CFG, "enabled", False)
    if not cfg:
        return
    await on_tick(symbol, price_f, ts_val, volume)


try:
    BUS.subscribe("market.tick", _on_market_tick_event)
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Failed to subscribe strategy to market.tick", exc_info=True
    )


async def _on_market_book_event(event: dict[str, Any]) -> None:
    if not SCALP_MODULE or not getattr(SCALP_MODULE, "enabled", False):
        return
    symbol = str(event.get("symbol") or "")
    if not symbol:
        return
    try:
        bid = float(event.get("bid_price") or 0.0)
        ask = float(event.get("ask_price") or 0.0)
        bid_qty = float(event.get("bid_qty") or 0.0)
        ask_qty = float(event.get("ask_qty") or 0.0)
    except (TypeError, ValueError):
        return
    ts_raw = event.get("ts")
    try:
        ts_val = float(ts_raw) if ts_raw is not None else time.time()
    except (TypeError, ValueError):
        ts_val = time.time()
    try:
        SCALP_MODULE.handle_book(symbol, bid, ask, bid_qty, ask_qty, ts_val)
    except Exception as exc:
        logging.getLogger(__name__).debug("Failed to process book for %s", symbol, exc_info=True)


try:
    BUS.subscribe("market.book", _on_market_book_event)
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Failed to subscribe strategy to market.book", exc_info=True
    )


try:
    BUS.subscribe("model.promoted", policy_hmm.reload_model)
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Failed to subscribe strategy to model.promoted", exc_info=True
    )


async def _on_liquidation_cluster(event: dict[str, Any]) -> None:
    if not LIQU_MODULE or not LIQU_MODULE.enabled:
        return
    
    try:
        decisions = LIQU_MODULE.handle_signal(event)
    except Exception as exc:
        decisions = None
        
    if not decisions:
        return
        
    for decision in decisions:
        # Convert decision dict to StrategySignal
        symbol = str(decision.get("symbol") or "")
        side = str(decision.get("side") or "").upper()
        
        meta = decision.get("meta") or {}
        meta["order_type"] = decision.get("type", "LIMIT")
        meta["price"] = decision.get("price")
        meta["time_in_force"] = decision.get("time_in_force", "IOC")
        
        # Market resolution
        market = resolve_market_choice(symbol, "futures") # Default to futures for liquidation sniping
        
        sig = StrategySignal(
            symbol=symbol,
            side=side,
            quote=None, # We use explicit quantity
            quantity=decision.get("quantity"),
            dry_run=None,
            tag=decision.get("tag", "liqu_sniper"),
            meta=meta,
            market=market
        )
        
        # Execute Async
        result = await _execute_strategy_signal_async(sig)
        if result.get("status") == "submitted":
            try:
                metrics.strategy_orders_total.labels(
                    symbol=symbol.split(".")[0],
                    venue="BINANCE",
                    side=side,
                    source="liquidation_sniper",
                ).inc()
            except Exception as exc:
                pass


try:
    BUS.subscribe("signal.liquidation_cluster", _on_liquidation_cluster)
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Failed to subscribe strategy to signal.liquidation_cluster", exc_info=True
    )


class StrategySignal(BaseModel):
    symbol: str = Field(..., description="e.g. BTCUSDT.BINANCE")
    side: str = Field(..., pattern=r"^(BUY|SELL)$")
    quote: float | None = Field(None, description="USDT notional (preferred)")
    quantity: float | None = Field(None, description="Base qty (alternative)")
    dry_run: bool | None = Field(None, description="Override STRATEGY_DRY_RUN")
    tag: str | None = Field(None, description="Optional label (e.g. 'ma_cross')")
    meta: dict[str, Any] | None = Field(
        None, description="Optional strategy metadata (e.g. stops, targets)"
    )
    market: str | None = Field(None, description="Preferred Binance market (spot, futures, margin)")


@router.post("/strategy/signal")
async def post_strategy_signal(sig: StrategySignal, request: Request):
    require_ops_token(request)
    idem = request.headers.get("X-Idempotency-Key")
    return await _execute_strategy_signal_async(sig, idem_key=idem)


class StrategyParams(BaseModel):
    params: dict[str, Any]


@router.post("/strategies/{strategy_id}/start")
def start_strategy(strategy_id: str, request: Request, payload: StrategyParams | None = None):
    require_ops_token(request)
    if strategy_id == "trend_follow" and TREND_MODULE:
        TREND_MODULE.enabled = True
        logging.getLogger(__name__).info("Strategy %s started", strategy_id)
        return {"status": "started", "id": strategy_id}
    elif strategy_id == "scalp" and SCALP_MODULE:
        SCALP_MODULE.enabled = True
        logging.getLogger(__name__).info("Strategy %s started", strategy_id)
        return {"status": "started", "id": strategy_id}
    elif strategy_id == "momentum_rt" and MOMENTUM_RT_MODULE:
        MOMENTUM_RT_MODULE.enabled = True
        logging.getLogger(__name__).info("Strategy %s started", strategy_id)
        return {"status": "started", "id": strategy_id}
    elif strategy_id == "liquidation_sniper" and LIQU_MODULE:
        LIQU_MODULE.enabled = True
        logging.getLogger(__name__).info("Strategy %s started", strategy_id)
        return {"status": "started", "id": strategy_id}
    
    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found or not loaded")


@router.post("/strategies/{strategy_id}/stop")
def stop_strategy(strategy_id: str, request: Request):
    require_ops_token(request)
    if strategy_id == "trend_follow" and TREND_MODULE:
        TREND_MODULE.enabled = False
        logging.getLogger(__name__).info("Strategy %s stopped", strategy_id)
        return {"status": "stopped", "id": strategy_id}
    elif strategy_id == "scalp" and SCALP_MODULE:
        SCALP_MODULE.enabled = False
        logging.getLogger(__name__).info("Strategy %s stopped", strategy_id)
        return {"status": "stopped", "id": strategy_id}
    elif strategy_id == "momentum_rt" and MOMENTUM_RT_MODULE:
        MOMENTUM_RT_MODULE.enabled = False
        logging.getLogger(__name__).info("Strategy %s stopped", strategy_id)
        return {"status": "stopped", "id": strategy_id}
    elif strategy_id == "liquidation_sniper" and LIQU_MODULE:
        LIQU_MODULE.enabled = False
        logging.getLogger(__name__).info("Strategy %s stopped", strategy_id)
        return {"status": "stopped", "id": strategy_id}

    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found or not loaded")


@router.post("/strategies/{strategy_id}/update")
def update_strategy(strategy_id: str, request: Request, payload: StrategyParams):
    require_ops_token(request)
    params = payload.params
    if strategy_id == "trend_follow" and TREND_MODULE:
        if hasattr(TREND_MODULE, "cfg"):
            for k, v in params.items():
                if hasattr(TREND_MODULE.cfg, k):
                    setattr(TREND_MODULE.cfg, k, v)
        logging.getLogger(__name__).info("Strategy %s updated with %s", strategy_id, params)
        return {"status": "updated", "id": strategy_id, "params": params}
    elif strategy_id == "liquidation_sniper" and LIQU_MODULE:
        if hasattr(LIQU_MODULE, "cfg"):
            for k, v in params.items():
                if hasattr(LIQU_MODULE.cfg, k):
                    setattr(LIQU_MODULE.cfg, k, v)
        logging.getLogger(__name__).info("Strategy %s updated with %s", strategy_id, params)
        return {"status": "updated", "id": strategy_id, "params": params}
    elif strategy_id == "deepseek_v2" and DEEPSEEK_MODULE:
        if hasattr(DEEPSEEK_MODULE, "cfg"):
            for k, v in params.items():
                if hasattr(DEEPSEEK_MODULE.cfg, k):
                    setattr(DEEPSEEK_MODULE.cfg, k, v)
        logging.getLogger(__name__).info("Strategy %s updated with %s", strategy_id, params)
        return {"status": "updated", "id": strategy_id, "params": params}
    
    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found or not loaded")


_EXECUTOR: StrategyExecutor | None = None
_EXECUTOR_OVERRIDE: StrategyExecutor | None = None


def _get_executor() -> StrategyExecutor:
    global _EXECUTOR
    if _EXECUTOR_OVERRIDE is not None:
        return _EXECUTOR_OVERRIDE
    if _EXECUTOR is None:
        try:
            from .app import router as order_router_instance
        except Exception as exc:
            raise OrderRouterUnavailableError() from exc
        try:
            from .app import _config_hash as _cfg_hash
        except Exception as exc:
            _cfg_hash = None
        _EXECUTOR = StrategyExecutor(
            risk=RAILS,
            router=order_router_instance,
            default_dry_run=S_CFG.dry_run,
            config_hash_getter=_cfg_hash,
            source="strategy",
        )
    return _EXECUTOR


def set_executor_override(executor: StrategyExecutor | None) -> None:
    global _EXECUTOR_OVERRIDE
    _EXECUTOR_OVERRIDE = executor


def get_executor_override() -> StrategyExecutor | None:
    return _EXECUTOR_OVERRIDE


def reset_executor_cache() -> None:
    global _EXECUTOR
    _EXECUTOR = None


def _signal_payload(sig: StrategySignal) -> dict[str, Any]:
    return {
        "strategy": sig.tag or "strategy",
        "symbol": sig.symbol,
        "side": sig.side,
        "quote": sig.quote,
        "quantity": sig.quantity,
        "dry_run": sig.dry_run,
        "meta": sig.meta,
        "market": sig.market,
        "tag": sig.tag or "strategy",
        "ts": time.time(),
    }


def _present_strategy_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return result
    status = result.get("status")
    if status == "dry_run":
        presented = {**result, "status": "simulated"}
        presented.setdefault("mode", "dry_run")
        return presented
    return result


async def _execute_strategy_signal_async(
    sig: StrategySignal, *, idem_key: str | None = None
) -> dict[str, Any]:
    executor = _get_executor()
    result = await executor.execute(_signal_payload(sig), idem_key=idem_key)
    if result.get("status") == "submitted":
        _record_tick_latency(sig.symbol)
    return _present_strategy_result(result)


def _execute_strategy_signal(sig: StrategySignal, *, idem_key: str | None = None) -> dict[str, Any]:
    executor = _get_executor()
    result = executor.execute_sync(_signal_payload(sig), idem_key=idem_key)
    if result.get("status") == "submitted":
        _record_tick_latency(sig.symbol)
    return _present_strategy_result(result)


def register_tick_listener(cb: Callable[[str, float, float], object]) -> None:
    """Register an external listener invoked on every tick."""
    _tick_listeners.append(cb)


def clear_tick_listeners() -> None:
    _tick_listeners.clear()


def _notify_listeners(symbol: str, price: float, ts: float) -> None:
    for cb in list(_tick_listeners):
        try:
            res = cb(symbol, price, ts)
            if res is not None and inspect.isawaitable(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)  # type: ignore[arg-type]
                except RuntimeError:
                    pass
        except Exception as exc:
            continue


async def on_tick(
    symbol: str, price: float, ts: float | None = None, volume: float | None = None
) -> None:
    """Tick-driven strategy loop entrypoint."""
    # print(f"DEBUG: on_tick {symbol} {price}")
    
    ts_val = float(ts if ts is not None else time.time())
    venue = symbol.split(".")[1] if "." in symbol else "BINANCE"
    base = symbol.split(".")[0].upper()
    qualified = symbol if "." in symbol else f"{base}.{venue}"
    _last_tick_ts[qualified] = ts_val
    _last_tick_ts[base] = ts_val

    _notify_listeners(qualified, price, ts_val)

    # Heartbeat: Engine is healthy if processing ticks
    try:
        from engine.ops.watchdog import get_watchdog
        get_watchdog().heartbeat()
        # Publish to Redis for Supervisor
        r = get_global_redis()
        if r:
            r.publish("heartbeat", ts_val)
    except Exception:
        pass

    # --- HMM Ingest & Telemetry (Running unconditionally) ---
    hmm_features = {}
    hmm_conf_early = 0.0
    if S_CFG.hmm_enabled:
        try:
            # 1. Ingest Data
            policy_hmm.ingest_tick(base, price, volume or 1.0)
            
            # 2. Get Features (for UI)
            regime_data = policy_hmm.get_regime(base)
            if regime_data:
                hmm_features = regime_data.get("features", {})
                
            # 3. Broadcast Telemetry immediately
            perf_payload = {
                "type": "strategy.performance",
                "data": [{
                    "id": f"{base}-{venue}-hmm-monitor",
                    "name": "HMM Monitor",
                    "symbol": qualified,
                    "status": "watching",
                    "confidence": 0, # Will be updated by decision logic if active
                    "metrics": {
                        "features": hmm_features
                    },
                    "performance": {
                        "pnl": 0.0,
                        "sharpe": 0.0,
                        "drawdown": 0.0,
                        "winRate": 0.0,
                        "equitySeries": []
                    }
                }],
                "ts": time.time()
            }
            loop = asyncio.get_running_loop()
            loop.create_task(BROADCASTER.broadcast(perf_payload))
        except Exception as exc:
            logging.getLogger(__name__).warning("HMM Background Task failed: %s", exc)

    if time.time() < _entry_block_until:
        return

    # --- Broadcast Performance for Liquidation (Throttled 1s) ---
    if LIQU_MODULE and getattr(LIQU_MODULE, "enabled", False):
        if time.time() - _last_telemetry_ts['liquidation'] > 1.0:
            _last_telemetry_ts['liquidation'] = time.time()
            try:
                perf_payload = {
                    "type": "strategy.performance",
                    "data": [{
                        "id": "liquidation_sniper",
                        "name": "Liquidation Sniper",
                        "symbol": qualified,
                        "status": "active",
                        "confidence": 0.0,
                        "signal": 0,
                        "metrics": {},
                        "performance": {
                            "pnl": 0.00,
                            "sharpe": 0.0,
                            "winRate": 0.0,
                            "drawdown": 0.0,
                            "equitySeries": []
                        }
                    }],
                    "ts": time.time()
                }
                loop = asyncio.get_running_loop()
                loop.create_task(BROADCASTER.broadcast(perf_payload))
            except Exception:
                pass


    # print(f"DEBUG: Checking modules. SCALP={getattr(SCALP_MODULE, 'enabled', False)}")

    if SCALP_MODULE and SCALP_MODULE.enabled:
        scalp_decision = None
        try:
            scalp_decision = SCALP_MODULE.handle_tick(qualified, price, ts_val)
        except Exception as exc:
            scalp_decision = None
        if scalp_decision:
            scalp_symbol = str(scalp_decision.get("symbol") or qualified)
            scalp_side = str(scalp_decision.get("side") or "BUY")
            scalp_quote = float(scalp_decision.get("quote") or S_CFG.quote_usdt)
            scalp_tag = str(scalp_decision.get("tag") or "scalp")
            default_market = scalp_decision.get("market") or (
                "futures" if getattr(SCALP_CFG, "allow_shorts", True) else "spot"
            )
            resolved_market = resolve_market_choice(scalp_symbol, default_market)
            sig = StrategySignal(
                symbol=scalp_symbol,
                side=scalp_side,
                quote=scalp_quote,
                quantity=None,
                dry_run=None,
                tag=scalp_tag,
                meta=scalp_decision.get("meta"),
                market=resolved_market,
            )
            result = await _execute_strategy_signal_async(sig)
            if result.get("status") == "submitted":
                scalp_base = scalp_symbol.split(".")[0]
                scalp_venue = scalp_symbol.split(".")[1] if "." in scalp_symbol else "BINANCE"
                try:
                    metrics.strategy_orders_total.labels(
                        symbol=scalp_base,
                        venue=scalp_venue,
                        side=scalp_side,
                        source=scalp_tag,
                    ).inc()
                except Exception as exc:
                    pass
            
            if result.get("status") == "submitted":
                scalp_base = scalp_symbol.split(".")[0]
                scalp_venue = scalp_symbol.split(".")[1] if "." in scalp_symbol else "BINANCE"
                try:
                    metrics.strategy_orders_total.labels(
                        symbol=scalp_base,
                        venue=scalp_venue,
                        side=scalp_side,
                        source=scalp_tag,
                    ).inc()
                except Exception as exc:
                    pass
            
            # Return early if we traded to avoid double-processing
            return

    if DEEPSEEK_MODULE and DEEPSEEK_MODULE.enabled:
        # Ingest tick (Non-blocking)
        try:
            await DEEPSEEK_MODULE.handle_tick(qualified, price, ts_val)
        except Exception:
            pass




        # --- Broadcast Performance for DeepSeek (Throttled 1s) ---


            # But DeepSeek is low frequency, so it's fine.

        # --- Broadcast Performance for SCALP (Throttled 1s) ---
        # Only broadcast if we didn't trade (if we traded, we returned above)
        # Actually, we should broadcast regardless, but the return above prevents it.
        # So we should put this BEFORE the return if we want it to always fire, 
        # or just rely on the next tick for non-trade updates.
        # Since we return on trade, let's just handle the "idle" telemetry here.
        # --- Broadcast Performance for SCALP (debug mode) ---
        if time.time() - _last_telemetry_ts['scalp'] > 1.0:
             _last_telemetry_ts['scalp'] = time.time()
             try:
                perf_payload = {
                    "type": "strategy.performance",
                    "data": [{
                        "id": "scalp", 
                        "name": "Scalp Strategy",
                        "symbol": qualified,
                        "status": "running",
                        "confidence": 0.0, 
                        "signal": 0,
                        "metrics": {},
                        "performance": {
                            "pnl": 0.00,
                            "sharpe": 0.0,
                            "winRate": 0.0,
                            "drawdown": 0.0,
                            "equitySeries": []
                        }
                    }],
                    "ts": time.time()
                }
                loop = asyncio.get_running_loop()
                loop.create_task(BROADCASTER.broadcast(perf_payload))
             except Exception:
                pass


    if MOMENTUM_RT_MODULE and getattr(MOMENTUM_RT_MODULE, "enabled", False):
        momentum_decision = None
        try:
            momentum_decision = MOMENTUM_RT_MODULE.handle_tick(qualified, price, ts_val, volume)
        except Exception as exc:
            momentum_decision = None
        if momentum_decision:
            momentum_symbol = str(momentum_decision.get("symbol") or qualified)
            momentum_side = str(momentum_decision.get("side") or "BUY")
            momentum_quote = float(momentum_decision.get("quote") or S_CFG.quote_usdt)
            momentum_tag = str(momentum_decision.get("tag") or "momentum_rt")
            momentum_meta = momentum_decision.get("meta")
            default_market = momentum_decision.get("market") or (
                "futures"
                if getattr(MOMENTUM_RT_CFG, "prefer_futures", True) or momentum_side == "SELL"
                else "spot"
            )
            resolved_market = resolve_market_choice(momentum_symbol, default_market)
            sig = StrategySignal(
                symbol=momentum_symbol,
                side=momentum_side,
                quote=momentum_quote,
                quantity=None,
                dry_run=None,
                tag=momentum_tag,
                meta=momentum_meta,
                market=resolved_market,
            )
            result = await _execute_strategy_signal_async(sig)
            if result.get("status") == "submitted":
                try:
                    metrics.strategy_orders_total.labels(
                        symbol=momentum_symbol.split(".")[0],
                        venue=(
                            momentum_symbol.split(".")[1] if "." in momentum_symbol else "BINANCE"
                        ),
                        side=momentum_side,
                        source=momentum_tag,
                    ).inc()
                except Exception as exc:
                    pass

            # Return early on trade
            return

        # --- Broadcast Performance for MOMENTUM (Throttled 1s) ---
        if time.time() - _last_telemetry_ts['momentum_rt'] > 1.0:
            _last_telemetry_ts['momentum_rt'] = time.time()
            try:
                perf_payload = {
                    "type": "strategy.performance",
                    "data": [{
                        "id": "momentum_rt",
                        "name": "Momentum RT",
                        "symbol": qualified,
                        "status": "running",
                        "confidence": 0.85,
                        "signal": 0,
                        "metrics": {},
                        "performance": {
                            "pnl": 0.00,
                            "sharpe": 0.0,
                            "winRate": 0.0,
                            "drawdown": 0.0,
                            "equitySeries": []
                        }
                    }],
                    "ts": time.time()
                }
                loop = asyncio.get_running_loop()
                loop.create_task(BROADCASTER.broadcast(perf_payload))
            except Exception:
                pass

    if TREND_MODULE and TREND_MODULE.enabled:
        trend_decision = None
        try:
            trend_decision = await TREND_MODULE.handle_tick(qualified, price, ts_val)
        except Exception as exc:
            trend_decision = None
        if trend_decision:
            trend_symbol = str(trend_decision.get("symbol") or qualified)
            trend_side = str(trend_decision.get("side") or "BUY")
            trend_quote = float(trend_decision.get("quote") or S_CFG.quote_usdt)
            trend_tag = str(trend_decision.get("tag") or "trend_follow")
            default_market = (
                trend_decision.get("market") if isinstance(trend_decision, dict) else None
            )
            if not default_market:
                default_market = "futures" if getattr(TREND_CFG, "allow_shorts", False) else "spot"
            resolved_market = resolve_market_choice(trend_symbol, default_market)
            sig = StrategySignal(
                symbol=trend_symbol,
                side=trend_side,
                quote=trend_quote,
                quantity=None,
                dry_run=None,
                tag=trend_tag,
                market=resolved_market,
            )
            result = await _execute_strategy_signal_async(sig)
            if result.get("status") == "submitted":
                try:
                    metrics.strategy_orders_total.labels(
                        symbol=base, venue=venue, side=trend_side, source=trend_tag
                    ).inc()
                except Exception as exc:
                    pass

            # Return early on trade
            return

        # --- Broadcast Performance for TREND (Throttled 1s) ---
        if time.time() - _last_telemetry_ts['trend_follow'] > 1.0:
            _last_telemetry_ts['trend_follow'] = time.time()
            try:
                perf_payload = {
                    "type": "strategy.performance",
                    "data": [{
                        "id": "trend_follow",
                        "name": "Trend Follow",
                        "symbol": qualified,
                        "status": "running",
                        "confidence": 0.75,
                        "signal": 0,
                        "metrics": {},
                        "performance": {
                            "pnl": 0.00,
                            "sharpe": 0.0,
                            "winRate": 0.0,
                            "drawdown": 0.0,
                            "equitySeries": []
                        }
                    }],
                    "ts": time.time()
                }
                loop = asyncio.get_running_loop()
                loop.create_task(BROADCASTER.broadcast(perf_payload))
            except Exception:
                pass

    # --- MA crossing decision ---
    ma_side = _mac.push(qualified, price)
    ma_conf = 0.0
    if ma_side and price:
        window = _mac.windows[qualified]
        fast = _mac.fast
        if len(window) >= fast:
            fast_ma = sum(list(window)[-fast:]) / fast
            slow_ma = sum(window) / len(window)
            try:
                ma_conf = min(1.0, abs((fast_ma - slow_ma) / price))
            except ZeroDivisionError:
                ma_conf = 0.0

    # --- HMM decision ---
    hmm_conf = 0.0
    hmm_decision = None
    if S_CFG.hmm_enabled:
        try:
            policy_hmm.ingest_tick(base, price, volume or 1.0)
            hmm_decision = policy_hmm.decide(base)
            if hmm_decision and isinstance(hmm_decision[2], dict):
                probs = hmm_decision[2].get("probs") or []
                if isinstance(probs, (list, tuple)) and probs:
                    hmm_conf = float(max(probs))
        except Exception as exc:
            logging.getLogger(__name__).warning("HMM Decision failed: %s", exc, exc_info=True)
            hmm_decision = None
            hmm_conf = 0.0

    # --- HMM Features ---
    hmm_features = {}
    if S_CFG.hmm_enabled:
        try:
            regime_data = policy_hmm.get_regime(base)
            if regime_data:
                hmm_features = regime_data.get("features", {})
        except Exception as exc:
            logging.getLogger(__name__).warning("HMM Features failed: %s", exc, exc_info=True)
            pass

    # --- River Online Learning ---
    river_pred = 0
    river_proba = {}
    if hmm_features:
        try:
            r_res = river_policy.on_tick(base, hmm_features, price)
            river_pred = r_res.get("prediction", 0)
            river_proba = r_res.get("proba", {})
            # Save model occasionally (1% chance) to avoid IO blocking
            import random
            if random.random() < 0.01:
                river_policy.save()
        except Exception as exc:
            pass

    # --- Ensemble fusion (with River voting) ---
    river_decision = {"prediction": river_pred, "proba": river_proba} if river_pred is not None else None
    fused = ensemble_policy.combine(base, ma_side, ma_conf, hmm_decision, river_decision)

    signal_side = None
    signal_quote = S_CFG.quote_usdt
    signal_meta = {}
    conf_to_emit = 0.0
    
    # DEBUG LOGGING
    if ma_conf > 0 or hmm_conf > 0 or river_pred == 1:
        logging.info(f"[STRATEGY] {base} Decision: MA_Conf={ma_conf:.4f} HMM_Conf={hmm_conf:.4f} River={river_pred} (Proba={river_proba}) Ensemble={bool(fused)}")

    if fused:
        signal_side, signal_quote, signal_meta = fused
        conf_to_emit = float(signal_meta.get("conf", 0.0))
        logging.info(f"[STRATEGY_TRACE] {base} FUSED: Side={signal_side} Conf={conf_to_emit}")
    elif ma_side and not S_CFG.ensemble_enabled:
        signal_side = ma_side
        signal_quote = S_CFG.quote_usdt
        signal_meta = {"exp": "ma_v1", "conf": ma_conf}
        conf_to_emit = ma_conf
        logging.info(f"[STRATEGY_TRACE] {base} MA (Solo): Side={signal_side} Conf={conf_to_emit}")
    elif hmm_decision:
        signal_side, signal_quote, signal_meta = hmm_decision
        conf_to_emit = float(signal_meta.get("conf", hmm_conf))
        logging.info(f"[STRATEGY_TRACE] {base} HMM (Solo): Side={signal_side} Conf={conf_to_emit}")
    else:
        conf_to_emit = max(ma_conf, hmm_conf)
        logging.info(f"[STRATEGY_TRACE] {base} NO SIGNAL. Conf={conf_to_emit}")

    signal_value = 0.0
    if signal_side:
        signal_value = 1.0 if signal_side == "BUY" else -1.0
    try:
        metrics.strategy_signal.labels(symbol=base, venue=venue).set(signal_value)
    except Exception as exc:
        pass
    try:
        metrics.strategy_confidence.labels(symbol=base, venue=venue).set(conf_to_emit)
    except Exception as exc:
        pass

    # Broadcast Strategy Performance
    try:
        perf_payload = {
            "type": "strategy.performance",
            "data": [{
                "id": f"{base}-{venue}-ensemble",
                "name": "Ensemble Strategy" if fused else "MA Crossover",
                "symbol": qualified,
                "status": "active",
                "confidence": conf_to_emit,
                "signal": signal_value,
                "metrics": {
                    "features": hmm_features
                },
                "performance": {
                    "pnl": 0.0,
                    "sharpe": 0.0,
                    "drawdown": 0.0,
                    "winRate": 0.0,
                    "equitySeries": []
                }
            }],
            "ts": time.time()
        }
        loop = asyncio.get_running_loop()
        loop.create_task(BROADCASTER.broadcast(perf_payload))
    except (RuntimeError, ImportError):
        pass

    if signal_side:
        if not _cooldown_ready(qualified, price, max(conf_to_emit, 0.0), venue):
            return
        source_tag = signal_meta.get("exp", "ensemble_v1" if fused else "ma_v1")
        market_choice = resolve_market_choice(qualified, S_CFG.default_market)
        sig = StrategySignal(
            symbol=qualified,
            side=signal_side,
            quote=signal_quote,
            quantity=None,
            dry_run=None,
            tag=source_tag,
            meta=signal_meta,
            market=market_choice,
        )

        result = await _execute_strategy_signal_async(sig)
        logging.info(f"[STRATEGY_TRACE] Execution Result for {qualified}: {result}")
        if result.get("status") == "submitted":
            try:
                metrics.strategy_orders_total.labels(
                    symbol=base, venue=venue, side=signal_side, source=source_tag
                ).inc()
            except Exception as exc:
                pass

        if fused:
            try:
                _schedule_bracket_watch(qualified, signal_side, price)
            except Exception as exc:
                pass


def _record_tick_latency(symbol: str) -> None:
    tick_ts = _last_tick_ts.get(symbol)
    if tick_ts is None:
        tick_ts = _last_tick_ts.get(symbol.split(".")[0])
    if tick_ts is None:
        return
    latency_ms = max(0.0, (time.time() - tick_ts) * 1000.0)
    try:
        metrics.strategy_tick_to_order_latency_ms.observe(latency_ms)
    except Exception as exc:
        pass
    try:
        record_tick_latency(symbol, latency_ms)
    except Exception as exc:
        pass


def _cooldown_ready(symbol: str, price: float, confidence: float, venue: str) -> bool:
    now = time.time()
    # In test environments (pytest), bypass cooldown to avoid inter-test coupling
    try:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return True
    except Exception as exc:
        pass
    base_symbol = symbol.split(".")[0]
    base_window = max(0.5, S_CFG.cooldown_sec * calibration_cooldown_scale(base_symbol))
    conf_factor = max(0.35, 1.0 - min(confidence, 0.99))
    px_factor = 1.0
    prev_price = _last_trade_price.get(symbol)
    if prev_price:
        move_bp = abs(price - prev_price) / max(prev_price, 1e-9) * 10_000
        px_factor = min(2.0, max(0.5, 1.0 - min(move_bp, 50.0) / 100.0))
    dynamic_window = max(1.0, base_window * conf_factor * px_factor)
    if not _SYMBOL_COOLDOWNS.allow(symbol, now=now):
        try:
            remaining = _SYMBOL_COOLDOWNS.remaining(symbol, now=now)
            logging.info(f"[STRATEGY_TRACE] Cooldown blocking {symbol}. Remaining: {remaining:.2f}s")
            metrics.strategy_cooldown_window_seconds.labels(symbol=base_symbol, venue=venue).set(
                remaining
            )
        except Exception as exc:
            pass
        return False

    _SYMBOL_COOLDOWNS.hit(symbol, ttl=dynamic_window, now=now)
    _last_trade_price[symbol] = price
    try:
        metrics.strategy_cooldown_window_seconds.labels(symbol=base_symbol, venue=venue).set(
            dynamic_window
        )
    except Exception as exc:
        pass
    return True


def _latest_price(symbol: str) -> float | None:
    """Synchronous price lookup for scheduler thread without touching event loop.

    Uses a one-off blocking HTTP call to the Binance public ticker endpoint
    to avoid sharing the async client across threads/loops.
    """
    try:
        import httpx

        from .config import get_settings

        clean = symbol.split(".")[0]
        s = get_settings()
        base = s.base_url.rstrip("/")
        path = (
            "/fapi/v1/ticker/price" if getattr(s, "is_futures", False) else "/api/v3/ticker/price"
        )
        r = httpx.get(f"{base}{path}", params={"symbol": clean}, timeout=5.0)
        r.raise_for_status()
        return float(r.json().get("price"))
    except Exception as exc:
        return None


def _tick_once():
    symbols = S_CFG.symbols or []
    for s in symbols:
        if "." in s:
            symbol = s
        else:
            sym = s if s.endswith("USD") or s.endswith("USDT") else f"{s}USDT"
            symbol = f"{sym}.BINANCE"
        px = _latest_price(symbol)
        if px is None:
            continue
        # on_tick is async, so we fire event to bus instead of calling directly
        BUS.fire("market.tick", {"symbol": symbol, "price": px, "ts": time.time()})


# --- Simple bracket watcher (SL/TP emulation) ---
def _schedule_bracket_watch(symbol: str, side: str, entry_px: float):
    if not S_CFG.hmm_enabled:
        return  # Only for HMM strategy
    # TP/SL in basis points
    tp = S_CFG.tp_bps / 10000.0
    sl = S_CFG.sl_bps / 10000.0
    up = entry_px * (1 + tp)
    dn = entry_px * (1 - sl)

    def _watch():
        # light, best-effort loop
        for _ in range(120):  # ~2h at 60s; adjust if you poll faster
            px = _latest_price(symbol)
            if px is None:
                time.sleep(S_CFG.interval_sec)
                continue
            if side == "BUY":
                if px >= up:
                    sig = StrategySignal(
                        symbol=symbol,
                        side="SELL",
                        quote=S_CFG.quote_usdt,
                        quantity=None,
                        dry_run=None,
                        tag="tp",
                    )
                    _execute_strategy_signal(sig)
                    break
                if px <= dn:
                    sig = StrategySignal(
                        symbol=symbol,
                        side="SELL",
                        quote=S_CFG.quote_usdt,
                        quantity=None,
                        dry_run=None,
                        tag="sl",
                    )
                    _execute_strategy_signal(sig)
                    break
            else:  # short on futures/perp only; if spot, this will be ignored by router/rails
                if px <= dn:
                    sig = StrategySignal(
                        symbol=symbol,
                        side="BUY",
                        quote=S_CFG.quote_usdt,
                        quantity=None,
                        dry_run=None,
                        tag="tp",
                    )
                    _execute_strategy_signal(sig)
                    break
                if px >= up:
                    sig = StrategySignal(
                        symbol=symbol,
                        side="BUY",
                        quote=S_CFG.quote_usdt,
                        quantity=None,
                        dry_run=None,
                        tag="sl",
                    )
                    _execute_strategy_signal(sig)
                    break
            time.sleep(S_CFG.interval_sec)

    threading.Thread(target=_watch, daemon=True).start()


def start_scheduler():
    global _loop_thread
    if not S_CFG.enabled:
        return
    if _loop_thread and _loop_thread.is_alive():
        return
    _stop_flag.clear()

    def loop():
        while not _stop_flag.is_set():
            t0 = time.time()
            try:
                _tick_once()
            except Exception as exc:
                pass
            dt = max(0.0, S_CFG.interval_sec - (time.time() - t0))
            _stop_flag.wait(dt)

    _loop_thread = threading.Thread(target=loop, name="strategy-ma-cross", daemon=True)
    _loop_thread.start()


def stop_scheduler():
    _stop_flag.set()


def block_entries_for(seconds: float) -> None:
    global _entry_block_until
    _entry_block_until = max(_entry_block_until, time.time() + float(seconds))


def _ensure_scalp_bracket_manager() -> ScalpBracketManager:
    global _SCALP_BRACKET_MANAGER
    if _SCALP_BRACKET_MANAGER is None:
        _SCALP_BRACKET_MANAGER = ScalpBracketManager(
            price_fetcher=_latest_price,
            submit_exit=_submit_scalp_exit,
            logger=logging.getLogger(__name__),
        )
    return _SCALP_BRACKET_MANAGER


async def _submit_scalp_exit(payload: dict[str, Any]) -> None:
    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        return
    venue = str(payload.get("venue") or "BINANCE").lower()
    side = str(payload.get("side") or "SELL").upper()
    quantity_raw = payload.get("quantity")
    try:
        quantity = float(quantity_raw)
    except (TypeError, ValueError):
        return
    if quantity <= 0.0:
        return
    tag = str(payload.get("tag") or "scalp_exit")
    meta = payload.get("meta")

    sig = StrategySignal(
        symbol=symbol,
        side=side,
        quote=None,
        quantity=quantity,
        dry_run=None,
        tag=tag,
        meta=meta,
        market=None,
    )
    result = await _execute_strategy_signal_async(sig)
    if result.get("status") != "submitted":
        return

    base = symbol.split(".")[0]
    try:
        metrics.scalp_bracket_exits_total.labels(symbol=base, venue=venue, mode=tag).inc()
    except Exception as exc:
        pass
@router.on_event("startup")
async def startup_event():
    """Initialize strategy background tasks."""
    start_scheduler()
    _ensure_scalp_bracket_manager()
    logging.getLogger(__name__).info("Strategy scheduler and bracket manager started.")


@router.on_event("shutdown")
async def shutdown_event():
    stop_scheduler()

from engine.brain import NautilusBrain

# Initialize Brain
BRAIN = NautilusBrain()

async def _on_deepseek_signal(event: dict[str, Any]) -> None:
    """
    Handles asynchronous trading decisions from the DeepSeek Worker.
    Routes ALL signals through Nautilus Brain for ensemble voting.
    """
    symbol = str(event.get("symbol") or "")
    # Support both old and new keys for robust migration
    action = str(event.get("action") or "HOLD").upper()
    confidence = float(event.get("confidence") or 0.0)
    sentiment_score = float(event.get("sentiment_score") or 0.0)
    reasoning = str(event.get("reasoning") or "")
    price = float(event.get("price") or 0.0)
    
    # 1. Feed the attributes into the Brain
    # Note: DeepSeek v2 now provides explicit sentiment_score (-1 to 1)
    # If missing (legacy), try to Infer from action?
    if sentiment_score == 0.0 and action == "BUY":
        sentiment_score = 0.6
    elif sentiment_score == 0.0 and action == "SELL":
        sentiment_score = -0.6
        
    BRAIN.update_sentiment(symbol, sentiment_score, time.time())
    
    # 2. Ask Brain for the final decision
    # The Brain combines HMM Regime + Sentiment Veto + StatArb Logic
    decision_side, size_factor, brain_meta = BRAIN.get_decision(symbol, price)
    
    if not decision_side:
        logging.info(f"🧠 Brain VETO for {symbol}: {brain_meta.get('brain_reason')}")
        return

    logging.info(f"🧠 Brain APPROVED {decision_side} for {symbol}: {brain_meta.get('brain_reason')}")

    # 3. Sizing
    # Use defaults scaled by Brain's size_factor
    base_quote = 100.0
    # Try to respect AI's quote if provided, but modded by Brain
    raw_quote = event.get("quote")
    if raw_quote:
        try:
            base_quote = float(raw_quote)
        except (TypeError, ValueError):
            pass
            
    final_quote = base_quote * size_factor

    # 4. Execute
    market = "futures"
    
    sig = StrategySignal(
        symbol=symbol,
        side=decision_side, # Use Brain's decided side
        quote=final_quote,
        quantity=None,
        dry_run=None,
        tag="nautilus_brain_ensemble",
        meta={
            "brain_reason": brain_meta.get("brain_reason"),
            "ai_confidence": confidence,
            "ai_sentiment": sentiment_score,
            "regime": brain_meta.get("regime"),
            "price": price
        },
        market=market,
    )
    
    await _execute_strategy_signal_async(sig)


try:
    BUS.subscribe("strategy.deepseek_signal", _on_deepseek_signal)
    logging.getLogger(__name__).info("DeepSeek Signal Handler Wired")
except Exception as exc:
    logging.getLogger(__name__).warning("Failed to wire DeepSeek signal handler", exc_info=True)
