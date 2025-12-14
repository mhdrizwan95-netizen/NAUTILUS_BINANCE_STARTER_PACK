"""FastAPI application for trading engine."""
from __future__ import annotations

# Install high-performance event loop BEFORE any asyncio imports
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass  # Fallback to standard asyncio

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from random import SystemRandom
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

import httpx as _httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

import engine.state as state_mod
from engine import metrics, strategy
from engine.strategy import SYMBOL_SCANNER
from engine.config import (
    QUOTE_CCY,
    get_settings,
    load_risk_config,
    load_strategy_config,
    norm_symbol,
)
from engine.core import alert_daemon
from engine.core.binance import BinanceMarginREST, BinanceREST
from engine.core.event_bus import (
    BUS,
    initialize_event_bus,
    publish_risk_event,
)

if TYPE_CHECKING:
    from engine.core.alert_daemon import AlertDaemon
from engine.core.order_router import OrderRouterExt, _MDAdapter, set_exchange_client
from engine.core.portfolio import Portfolio, Position
from engine.core.signal_queue import SIGNAL_QUEUE, QueuedEvent
from engine.events.publisher import publish_external_event
from engine.events.schemas import ExternalEvent
from engine.feeds.market_data_dispatcher import MarketDataDispatcher, MarketDataLogger
from engine.idempotency import CACHE, append_jsonl
from engine.logging_utils import (
    bind_request_id,
    reset_request_context,
    setup_logging,
)
from engine.middleware.redaction import RedactionMiddleware
from engine.ops.bracket_governor import BracketGovernor
from engine.ops.stop_validator import StopValidator
from engine.ops_auth import require_ops_token
from engine.reconcile import reconcile_since_snapshot
from engine.risk import RiskRails
from engine.runtime import tasks as runtime_tasks
from engine.services.model_watcher import ModelPromotionWatcher
from engine.services.param_client import (
    ParamControllerBridge,
    bootstrap_param_client,
    get_param_client,
)
from engine.services.price_bridge import PriceBridge
from engine.services.liquidation_watcher import LiquidationWatcher
from engine.state import SnapshotStore
from engine.state import SnapshotStore
from engine.universe import configured_universe, last_prices
from engine.core.binance_market_stream import BinanceMarketStream
from engine.core.binance_user_stream import BinanceUserStream
from engine.services.telemetry_broadcaster import BROADCASTER
from shared.dry_run import install_dry_run_guard, log_dry_run_banner
from shared.time_guard import check_clock_skew
from fastapi import WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager


SERVICE_NAME = os.getenv("OBS_SERVICE_NAME", "engine")
_ENGINE_START_TS = time.time()
_PRICE_BRIDGE: PriceBridge | None = None
_LIQUIDATION_WATCHER: LiquidationWatcher | None = None
_app_logger = logging.getLogger("engine.app")
_JITTER_RNG = SystemRandom()




_SafelyResult = TypeVar("_SafelyResult")
_RequestHandler = Callable[[Request], Awaitable[Response]]
_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    ModuleNotFoundError,
    ImportError,
    asyncio.TimeoutError,
)
MODEL_TAG = os.getenv("MODEL_TAG", "hmm_v1")


def _safely(
    context: str,
    func: Callable[..., _SafelyResult],
    *args: Any,
    **kwargs: Any,
) -> _SafelyResult | None:
    """Invoke callable while logging (instead of swallowing) any exception."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        _app_logger.warning("%s failed: %s", context, exc, exc_info=True)
        return None


def _log_suppressed(context: str, exc: Exception) -> None:
    """Record intentionally suppressed exceptions for observability."""
    _app_logger.debug("%s suppressed exception: %s", context, exc, exc_info=True)


class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: _RequestHandler) -> Response:
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = req_id
        token = bind_request_id(req_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_context(token)
        try:
            response.headers["X-Request-ID"] = req_id
        except (
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:  # pragma: no cover - header mutation failure
            _log_suppressed("attach X-Request-ID header", exc)
        return response


class _HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: _RequestHandler) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = time.perf_counter() - start
            metrics.observe_http_request(
                SERVICE_NAME, request.method, _route_template(request), 500, duration
            )
            raise
        duration = time.perf_counter() - start
        metrics.observe_http_request(
            SERVICE_NAME,
            request.method,
            _route_template(request),
            response.status_code,
            duration,
        )
        return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route and getattr(route, "path", None):
        return route.path
    return request.url.path


app = FastAPI(title="HMM Engine", version="0.1.0")
install_dry_run_guard(app, allow_paths={"/health", "/metrics", "/metrics/prometheus"})
log_dry_run_banner("engine.app")
app.add_middleware(_RequestIDMiddleware)
app.add_middleware(_HttpMetricsMiddleware)
app.add_middleware(RedactionMiddleware)


# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # Fire and forget broadcast to avoid blocking
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                pass

_WS_MANAGER = ConnectionManager()

async def _telemetry_bridge():
    """Forward internal BROADCASTER events to WebSocket clients."""
    queue = await BROADCASTER.subscribe()
    try:
        while True:
            payload = await queue.get()
            await _WS_MANAGER.broadcast(payload)
            queue.task_done()
    except asyncio.CancelledError:
        BROADCASTER.unsubscribe(queue)

@app.on_event("startup")
async def start_ws_bridge():
    loop = asyncio.get_running_loop()
    loop.create_task(_telemetry_bridge())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Simple token auth
    token = websocket.query_params.get("token")
    # TODO: Validate token against OPS_API_TOKEN if needed. 
    # For now, we accept connections to facilitate the "Glass Cockpit" demo.
    
    await _WS_MANAGER.connect(websocket)
    try:
        while True:
            # Keep alive / handle incoming (e.g. subscriptions)
            data = await websocket.receive_json()
            if data.get("type") == "heartbeat":
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
    except WebSocketDisconnect:
        _WS_MANAGER.disconnect(websocket)
    except Exception as exc:
        _WS_MANAGER.disconnect(websocket)



@app.on_event("startup")
async def _clock_skew_probe() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: check_clock_skew("engine"))


@app.on_event("startup")
async def _bootstrap_services() -> None:
    # Bootstrap Param Client
    param_url = os.getenv("PARAM_CONTROLLER_URL", "")
    if param_url:
        client = bootstrap_param_client(param_url)
        if client:
            await client.start()
            client.wire_feedback(BUS)
            _app_logger.info("Param client started and feedback wired")

    # Start PriceBridge
    ops_url = os.getenv("OPS_BASE", "http://ops:8002")
    ops_token = os.getenv("OPS_API_TOKEN", "dev-token")
    global _PRICE_BRIDGE
    _PRICE_BRIDGE = PriceBridge()
    await _PRICE_BRIDGE.start()

    # [Institutional Upgrade] Start Liquidation Watcher
    global _LIQUIDATION_WATCHER
    _LIQUIDATION_WATCHER = LiquidationWatcher(BUS)
    await _LIQUIDATION_WATCHER.start()


@app.on_event("shutdown")
async def _shutdown_services() -> None:
    if _market_stream:
        _market_stream.stop()

    try:
        from engine.services.param_client import get_param_client
        pc = get_param_client()
        if pc:
            await pc.stop()
    except Exception:
        pass

    global _PRICE_BRIDGE
    if _PRICE_BRIDGE:
        await _PRICE_BRIDGE.stop()
        
    global _LIQUIDATION_WATCHER
    if _LIQUIDATION_WATCHER:
        await _LIQUIDATION_WATCHER.stop()


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


settings = get_settings()
ROLE = os.getenv("ROLE", "trader").lower()
IS_EXPORTER = ROLE == "exporter"
VENUE = "BINANCE"
risk_cfg = load_risk_config()
RAILS = RiskRails(risk_cfg)
EXTERNAL_EVENTS_SECRET = os.getenv("EXTERNAL_EVENTS_SECRET", "")
EXTERNAL_EVENTS_ENABLED = bool(EXTERNAL_EVENTS_SECRET)
_EXTERNAL_SIGNATURE_HEADER = "X-Events-Signature"
_market_data_dispatcher: MarketDataDispatcher | None = None
_market_data_logger: MarketDataLogger | None = None
try:
    MIN_FUT_BAL_USDT = float(os.getenv("MIN_FUT_BAL_USDT", "300"))
except (TypeError, ValueError):
    MIN_FUT_BAL_USDT = 300.0
try:
    TOPUP_CHUNK_USDT = float(os.getenv("TOPUP_CHUNK_USDT", "500"))
except (TypeError, ValueError):
    TOPUP_CHUNK_USDT = 500.0
try:
    AUTO_TOPUP_PERIOD_SEC = float(os.getenv("AUTO_TOPUP_PERIOD_SEC", "45"))
except (TypeError, ValueError):
    AUTO_TOPUP_PERIOD_SEC = 45.0
AUTO_TOPUP_PERIOD_SEC = max(5.0, AUTO_TOPUP_PERIOD_SEC)
try:
    WALLET_REFRESH_PERIOD_SEC = float(os.getenv("WALLET_REFRESH_PERIOD_SEC", "30"))
except (TypeError, ValueError):
    WALLET_REFRESH_PERIOD_SEC = 30.0
WALLET_REFRESH_PERIOD_SEC = max(5.0, WALLET_REFRESH_PERIOD_SEC)
AUTO_TOPUP_ENABLED = os.getenv("AUTO_TOPUP_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_AUTO_TOPUP_LOG = logging.getLogger("engine.auto_topup")
_WALLET_LOG = logging.getLogger("engine.wallet_balance")
_wallet_state_lock = Lock()
_wallet_state: dict[str, float] = {}


def _update_wallet_state(snapshot: dict[str, float]) -> None:
    with _wallet_state_lock:
        _wallet_state.clear()
        _wallet_state.update(snapshot)


def _wallet_state_copy() -> dict[str, float]:
    with _wallet_state_lock:
        return dict(_wallet_state)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class _DummyBinanceREST:
    """Lightweight offline stub used when API credentials are absent."""

    def __init__(self) -> None:
        self._price = float(os.getenv("DUMMY_BINANCE_PRICE", "20000"))

    async def account_snapshot(self, market: str | None = None) -> dict[str, Any]:
        return {
            "balances": [{"asset": "USDT", "free": 1000.0, "locked": 0.0}],
            "positions": [],
        }

    async def submit_market_quote(
        self, symbol: str, side: str, quote: float, market: str | None = None
    ) -> dict[str, Any]:
        qty = float(quote) / self._price if self._price else float(quote)
        return {
            "symbol": symbol,
            "executedQty": qty,
            "filled_qty_base": qty,
            "avg_fill_price": self._price,
            "status": "FILLED",
        }

    async def submit_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market: str | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        qty = float(quantity)
        return {
            "symbol": symbol,
            "executedQty": qty,
            "filled_qty_base": qty,
            "avg_fill_price": self._price,
            "status": "FILLED",
        }

    async def close(self) -> None:
        return None

    def get_last_price(self, symbol: str, market: str | None = None) -> float:
        price = self.ticker_price(symbol)
        if isinstance(price, dict):
            return float(price.get("price", self._price))
        try:
            return float(price)
        except (TypeError, ValueError):
            return self._price

    def ticker_price(self, symbol: str, market: str | None = None) -> dict[str, float]:
        return {"price": self._price}

    def my_trades_since(self, symbol: str, start_ms: int) -> list[dict[str, Any]]:
        return []

    async def order_status(
        self,
        symbol: str,
        *,
        order_id: int | str | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "orderId": order_id or 0,
            "status": "FILLED",
            "executedQty": float("nan"),
            "avgPrice": self._price,
        }

    async def safe_price(self, symbol: str) -> float:
        _ = symbol
        return self._price

    async def exchange_filter(self, symbol: str) -> Any:
        _ = symbol

        class _Filter:
            step_size = 0.0001
            min_qty = 0.0001
            min_notional = 5.0
            max_notional = 1_000_000.0
            tick_size = 0.0001

        return _Filter()

    async def refresh_portfolio(self) -> None:
        return None

    async def bulk_premium_index(self) -> dict[str, Any]:
        return {}

    async def account(self) -> dict[str, Any]:
        return {}

    async def position_risk(self) -> list[dict[str, Any]]:
        return []

    async def hedge_mode(self) -> bool:
        return False


RestClient = BinanceREST | _DummyBinanceREST

rest_client: Any
if not settings.api_key or not settings.api_secret:
    rest_client = _DummyBinanceREST()
else:
    rest_client = BinanceREST()

margin_rest_client: BinanceMarginREST | None
if _truthy_env("MARGIN_ENABLED") or _truthy_env("BINANCE_MARGIN_ENABLED"):
    if settings.api_key and settings.api_secret:
        try:
            margin_rest_client = BinanceMarginREST()
            set_exchange_client("BINANCE_MARGIN", margin_rest_client)
        except Exception as exc:
            logging.getLogger("engine.startup").warning(
                "[STARTUP] Failed to initialize margin REST client: %s", margin_exc
            )
            margin_rest_client = None
    else:
        margin_rest_client = None
else:
    margin_rest_client = None

MARGIN_REST = margin_rest_client


_START_TIME = time.time()


# ---- Binance WebSocket mark handler -----------------------------------------
_binance_mark_ts: dict[str, float] = {}
_BINANCE_WS_SYMBOLS: list[str] = []


def _apply_binance_mark_metrics(base: str, price: float) -> None:
    metrics.MARK_PRICE.labels(symbol=base, venue="binance").set(price)
    metrics.mark_price_by_symbol.labels(symbol=base).set(price)
    metrics.mark_price_freshness_sec.labels(symbol=base, venue="binance").set(0.0)
    _price_map[base] = price


async def _binance_on_mark(qual: str, sym: str, price: float, ts: float) -> None:
    base = sym.split(".")[0].upper() if "." in sym else sym.upper()
    try:
        price_f = float(price)
        if price_f <= 0:
            return
    except (TypeError, ValueError) as exc:
        _log_suppressed("binance mark price cast", exc)
        return
    _binance_mark_ts[base] = ts or time.time()

    _safely(f"binance mark metrics ({base})", _apply_binance_mark_metrics, base, price_f)
    
    try:
        await _maybe_emit_strategy_tick(
            qual,
            price_f,
            ts=ts or time.time(),
            source="binance_ws",
            stream="ws",
        )
    except Exception as exc:
        _log_suppressed(f"binance strategy tick ({base})", exc)


async def auto_topup_worker() -> None:
    """Background loop to keep USDⓈ-M balance topped up from Funding."""
    if not AUTO_TOPUP_ENABLED:
        _AUTO_TOPUP_LOG.info("auto_topup: disabled via env")
        return
    if VENUE != "BINANCE":
        _AUTO_TOPUP_LOG.info("auto_topup: skipping (venue=%s)", VENUE)
        return
    period = AUTO_TOPUP_PERIOD_SEC
    rest = BinanceREST(market="futures")
    _AUTO_TOPUP_LOG.info(
        "auto_topup: loop started (min=%.2f, chunk=%.2f, period=%.1fs)",
        MIN_FUT_BAL_USDT,
        TOPUP_CHUNK_USDT,
        period,
    )
    while True:
        try:
            result = await rest.ensure_futures_balance(
                min_fut_usdt=MIN_FUT_BAL_USDT,
                topup_chunk_usdt=TOPUP_CHUNK_USDT,
                asset="USDT",
            )
            if result.get("ok") and not result.get("skipped"):
                _AUTO_TOPUP_LOG.info("auto_topup: transfer result=%s", result)
            elif not result.get("ok"):
                _AUTO_TOPUP_LOG.warning("auto_topup: transfer error=%s", result)
        except asyncio.CancelledError:
            _AUTO_TOPUP_LOG.info("auto_topup: worker cancelled")
            raise
        except (TimeoutError, _httpx.HTTPError, ValueError, RuntimeError) as exc:
            _AUTO_TOPUP_LOG.warning("auto_topup: failure: %s", exc, exc_info=True)
        await asyncio.sleep(period)


async def wallet_balance_worker() -> None:
    """Poll Binance for wallet balances and expose them via engine metrics."""
    if VENUE != "BINANCE":
        _WALLET_LOG.warning("wallet monitor: skipping (venue=%s)", VENUE)
        return
    if IS_EXPORTER:
        _WALLET_LOG.warning("wallet monitor: disabled for exporter role")
        return
    if not (settings.api_key and settings.api_secret):
        _WALLET_LOG.warning("wallet monitor: missing Binance credentials; disabled")
        return
    rest = BinanceREST(market="futures")
    period = WALLET_REFRESH_PERIOD_SEC
    _WALLET_LOG.warning("wallet monitor: started (period=%.1fs)", period)

    def _as_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    rest_errors = (_httpx.HTTPError, asyncio.TimeoutError, ValueError, RuntimeError)

    while True:
        try:
            timestamp = time.time()
            futures_total = futures_available = 0.0
            try:
                futures_snapshot = await rest.account_snapshot(market="futures")
                futures_total = _as_float(futures_snapshot.get("totalWalletBalance"))
                futures_available = _as_float(futures_snapshot.get("availableBalance"))
            except rest_errors as fut_exc:
                _WALLET_LOG.debug("wallet monitor: futures snapshot failed (%s)", fut_exc)

            spot_free = spot_locked = 0.0
            spot_snapshot: dict[str, Any] = {}
            margin_level = 0.0
            margin_liability_usd = 0.0
            try:
                if _truthy_env("MARGIN_ENABLED") or _truthy_env("BINANCE_MARGIN_ENABLED"):
                    margin_snapshot = await rest.margin_account()
                    margin_level = _as_float(margin_snapshot.get("marginLevel"))
                    liability_btc = _as_float(margin_snapshot.get("totalLiabilityOfBtc"))
                    if liability_btc > 0:
                        try:
                            btc_px = float(await rest.ticker_price("BTCUSDT", market="spot"))
                        except rest_errors:
                            fallback = spot_snapshot.get("lastPrice") if spot_snapshot else 0.0
                            btc_px = _as_float(fallback)
                        margin_liability_usd = liability_btc * btc_px
            except rest_errors as margin_exc:
                _WALLET_LOG.debug("wallet monitor: margin snapshot failed (%s)", margin_exc)

            try:
                spot_snapshot = await rest.account_snapshot(market="spot") or {}
                for balance in spot_snapshot.get("balances", []) or []:
                    if str(balance.get("asset", "")).upper() == "USDT":
                        spot_free = _as_float(balance.get("free"))
                        spot_locked = _as_float(balance.get("locked"))
                        break
            except rest_errors as spot_exc:
                _WALLET_LOG.debug("wallet monitor: spot snapshot failed (%s)", spot_exc)

            funding_free = 0.0
            try:
                funding_free = _as_float(await rest.funding_balance("USDT"))
            except rest_errors as fund_exc:
                _WALLET_LOG.debug("wallet monitor: funding balance failed (%s)", fund_exc)

            spot_total = spot_free + spot_locked
            total_equity = futures_total + funding_free + spot_total
            snapshot = {
                "timestamp": timestamp,
                "futures_wallet_usdt": futures_total,
                "futures_available_usdt": futures_available,
                "funding_free_usdt": funding_free,
                "spot_free_usdt": spot_free,
                "spot_locked_usdt": spot_locked,
                "spot_total_usdt": spot_total,
                "margin_level": margin_level,
                "margin_liability_usd": margin_liability_usd,
                "total_equity_usdt": total_equity,
            }
            _update_wallet_state(snapshot)

            def _apply_portfolio(
                *,
                _total_equity: float = total_equity,
                _funding_free: float = funding_free,
                _spot_total: float = spot_total,
                _futures_available: float = futures_available,
                _margin_level: float = margin_level,
                _margin_liability_usd: float = margin_liability_usd,
                _snapshot: dict[str, Any] = snapshot,
            ) -> None:
                state = portfolio.state
                state.equity = _total_equity
                state.cash = _funding_free + _spot_total + _futures_available
                state.margin_level = _margin_level
                state.margin_liability_usd = _margin_liability_usd
                state.wallet_breakdown = dict(_snapshot)

            _safely("wallet monitor portfolio update", _apply_portfolio)
            _safely("wallet monitor margin metric", metrics.margin_level.set, float(margin_level))
            _safely(
                "wallet monitor liability metric",
                metrics.margin_liability_usd.set,
                float(margin_liability_usd),
            )
        except asyncio.CancelledError:
            _WALLET_LOG.warning("wallet monitor: cancelled")
            raise
        except rest_errors as exc:
            _WALLET_LOG.warning("wallet monitor: error: %s", exc, exc_info=True)
        await asyncio.sleep(period)


def _broadcast_telemetry(snapshot: dict[str, Any]) -> None:
    payload = {
        "type": "account_update",
        "data": snapshot,
        "ts": time.time()
    }
    # Fire and forget broadcast
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(BROADCASTER.broadcast(payload))
    except RuntimeError:
        pass


async def _broadcast_market_tick(event: dict[str, Any]) -> None:
    """Forward market ticks to WebSocket clients."""
    payload = {
        "type": "market.tick",
        "data": event,
        "ts": time.time()
    }
    await BROADCASTER.broadcast(payload)



async def _broadcast_market_trade(event: dict[str, Any]) -> None:
    """Forward market trades to WebSocket clients."""
    payload = {
        "type": "trade",
        "data": event,
        "ts": time.time()
    }
    await BROADCASTER.broadcast(payload)


async def _broadcast_strategy_performance(event: dict[str, Any]) -> None:
    """Forward strategy performance metrics to WebSocket clients."""
    payload = {
        "type": "strategy.performance",
        "data": event,
        "ts": time.time()
    }
    await BROADCASTER.broadcast(payload)


# Wire up telemetry
BUS.subscribe("market.tick", _broadcast_market_tick)
BUS.subscribe("market.trade", _broadcast_market_trade)
BUS.subscribe("strategy.performance", _broadcast_strategy_performance)

portfolio = Portfolio(on_update=_broadcast_telemetry)
router = OrderRouterExt(rest_client, portfolio, venue=VENUE, rails=RAILS)
order_router = router
try:
    # Expose BUS on router for event publishing (e.g., trade.fill)
    router.bus = BUS  # type: ignore[attr-defined]
except AttributeError as exc:  # pragma: no cover - defensive guard
    _log_suppressed("attach BUS to router", exc)
startup_lock = asyncio.Lock()
_PARAM_BRIDGE: ParamControllerBridge | None = None
_MODEL_WATCHER: ModelPromotionWatcher | None = None
_refresh_logger = logging.getLogger("engine.refresh")
_startup_logger = logging.getLogger("engine.startup")
_persist_logger = logging.getLogger("engine.persistence")


store = None
try:
    from engine.storage import sqlite as _sqlite_store

    
    _schedule_startup_event()
    store = _sqlite_store

    _persist_logger.info(
        "SQLite persistence initialized at %s", Path("data/runtime/trades.db").resolve()
    )
except Exception as exc:
    _persist_logger.exception("SQLite initialization failed")

# Attach metrics router
app.include_router(metrics.router)
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
_safely("set max notional metric", metrics.set_max_notional, RAILS.cfg.max_notional_usdt)
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)

_stop_validator: StopValidator | None = None
_LISTING_SNIPER = None
_MOMENTUM_BREAKOUT = None
_MEME_SENTIMENT = None
_AIRDROP_PROMO = None

# Attach strategy router only for trading role
if not IS_EXPORTER:
    app.include_router(strategy.router)


def _safe_float(value: Any) -> float | None:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val):
        return None
    return val


def _config_hash() -> str:
    """Generate stable hash of key config for provenance tracking."""
    keys = [
        "TRADING_ENABLED",
        "MIN_NOTIONAL_USDT",
        "MAX_NOTIONAL_USDT",
        "MAX_ORDERS_PER_MIN",
        "TRADE_SYMBOLS",
        "DUST_THRESHOLD_USD",
        "EXPOSURE_CAP_SYMBOL_USD",
        "EXPOSURE_CAP_TOTAL_USD",
        "VENUE_ERROR_BREAKER_PCT",
        "VENUE_ERROR_WINDOW_SEC",
    ]
    import os

    blob = "|".join(f"{k}={os.getenv(k, '')}" for k in keys)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


async def _maybe_emit_strategy_tick(
    symbol: str,
    price: float,
    *,
    ts: float | None = None,
    source: str | None = None,
    stream: str | None = None,
    volume: float | None = None,
) -> None:
    """Forward mark updates into the strategy loop when enabled."""
    if price is None or price <= 0:
        return
    event_ts = ts or time.time()
    qualified = symbol if "." in symbol else f"{symbol}.BINANCE"
    base = qualified.split(".")[0].upper()
    venue = qualified.split(".")[1].upper() if "." in qualified else "BINANCE"

    def _inc_strategy_tick_metric() -> None:
        metrics.strategy_ticks_total.labels(symbol=base, venue=venue.lower()).inc()

    _safely(f"strategy tick metric increment ({base})", _inc_strategy_tick_metric)

    payload: dict[str, Any] = {
        "symbol": qualified,
        "base": base,
        "venue": venue,
        "price": float(price),
        "ts": event_ts,
    }
    if source:
        payload["source"] = source
    if stream:
        payload["stream"] = stream
    if volume is not None:
        try:
            payload["volume"] = float(volume)
        except (TypeError, ValueError):
            payload["volume"] = None

    skip_bus = source == "binance_ws" and _market_data_dispatcher is not None
    delivered_via_bus = False
    if not skip_bus:

        def _fire_bus() -> None:
            BUS.fire("market.tick", payload)

        _safely(f"strategy tick BUS emit ({base})", _fire_bus)
        delivered_via_bus = bool(getattr(BUS, "_running", False))

    if skip_bus or delivered_via_bus:
        return

    cfg = getattr(strategy, "S_CFG", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return

    try:
        await strategy.on_tick(
            qualified,
            float(price),
            event_ts,
            volume,
        )
    except Exception as exc:
        _log_suppressed(f"strategy on_tick ({qualified})", exc)


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    """Lightweight readiness probe with only in-process checks."""
    snap_ok = bool(getattr(router, "snapshot_loaded", False))
    return {"ok": True, "snapshot_loaded": snap_ok, "mode": settings.mode}


@app.get("/version")
def version() -> dict[str, Any]:
    """Return build provenance and model info."""
    import os

    return {
        "git_sha": os.getenv("GIT_SHA", "dev"),
        "model_tag": os.getenv("MODEL_TAG", "hmm_v1"),
        "config_hash": _config_hash(),
        "build_at": os.getenv("BUILD_AT", ""),
    }


_external_event_logger = logging.getLogger("engine.api.external_events")

if not EXTERNAL_EVENTS_ENABLED:
    _external_event_logger.warning(
        "EXTERNAL_EVENTS_SECRET not set; /events/external endpoint disabled"
    )


class EmptySourceError(ValueError):
    """Raised when external event payloads omit the source."""

    def __init__(self) -> None:
        super().__init__("source must be non-empty")


class MutuallyExclusiveOrderFieldError(ValueError):
    """Raised when both quote and quantity are provided (or missing)."""

    def __init__(self) -> None:
        super().__init__("Set exactly one of quote or quantity.")


def _verify_external_signature(body: bytes, header_value: str) -> bool:
    if not EXTERNAL_EVENTS_ENABLED:
        return False
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(EXTERNAL_EVENTS_SECRET.encode(), body, hashlib.sha256).hexdigest()
    received = header_value.split("=", 1)[1]
    return hmac.compare_digest(expected, received)


@app.post("/events/external", status_code=202)
async def ingest_external_event(
    request: Request,
    x_events_signature: str = Header(default="", alias=_EXTERNAL_SIGNATURE_HEADER),
) -> dict[str, Any]:
    """Ingress point for external (off-tick) strategy signals."""

    if not EXTERNAL_EVENTS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="external event ingestion disabled (missing EXTERNAL_EVENTS_SECRET)",
        )

    raw_body = await request.body()
    if not _verify_external_signature(raw_body, x_events_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        envelope = ExternalEvent.model_validate_json(raw_body).with_default_id()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    try:
        event_id = await publish_external_event(envelope)
    except Exception as exc:
        metrics.external_feed_errors_total.labels(envelope.source).inc()
        _external_event_logger.warning(
            "Failed to enqueue external event from %s: %s",
            envelope.source,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="failed to enqueue external event") from exc

    return {"status": "queued", "id": event_id, "topic": "events.external_feed"}


_store = SnapshotStore(state_mod.SNAP_PATH)
_boot_status = {"snapshot_loaded": False, "reconciled": False}
_last_reconcile_ts = 0.0  # Track reconcile freshness
_last_specs_refresh = 0.0  # Track venue specs freshness
_basis_cache: dict[str, dict[str, float]] = (
    {}
)  # {symbol: {entry_price, position_amt, last_sync_epoch}}
# Track last symbols we emitted per-symbol metrics for cleanup when positions close
_last_position_symbols: set[str] = set()
_price_map: dict[str, float] = {}  # symbol -> markPrice
_snapshot_counter = 0


class ExternalEventRequest(BaseModel):
    """Schema for enqueuing external feed events via the API."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Canonical feed identifier")
    payload: dict[str, Any] = Field(default_factory=dict, description="Arbitrary event payload")
    asset_hints: list[str] = Field(
        default_factory=list, description="Optional trading symbols impacted"
    )
    priority: float = Field(0.5, ge=0.0, le=1.0, description="Queue priority [0.0, 1.0]")
    expires_at: float | None = Field(
        default=None,
        description="Optional epoch timestamp at which the event becomes stale",
    )
    ttl_sec: float | None = Field(
        default=None, ge=0.0, description="Alternative to expires_at: TTL in seconds"
    )

    @field_validator("source")
    @classmethod
    def _normalize_source(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise EmptySourceError
        return cleaned

    @field_validator("payload", mode="before")
    @classmethod
    def _default_payload(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return cast(dict[str, Any], value)

    @field_validator("asset_hints", mode="before")
    @classmethod
    def _coerce_hints(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, bytes):
            return [value.decode("utf-8", errors="ignore")]
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        return [str(value)]

    @field_validator("asset_hints", mode="after")
    @classmethod
    def _normalize_hints(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            normalized.append(text.upper())
        return normalized


_external_event_logger = logging.getLogger("engine.api.external_events")


async def _queue_external_event(evt: ExternalEventRequest) -> None:
    expires_at = evt.expires_at
    if expires_at is None and evt.ttl_sec is not None:
        expires_at = time.time() + float(evt.ttl_sec)

    event = {
        "source": evt.source,
        "payload": evt.payload,
        "asset_hints": evt.asset_hints,
        "priority": float(evt.priority),
    }
    if expires_at is not None:
        event["expires_at"] = float(expires_at)

    await SIGNAL_QUEUE.put(
        QueuedEvent(
            topic="events.external_feed",
            data=event,
            priority=float(evt.priority),
            expires_at=float(expires_at) if expires_at is not None else None,
            source=evt.source,
        )
    )
    metrics.external_feed_events_total.labels(evt.source).inc()
    metrics.external_feed_last_event_epoch.labels(evt.source).set(time.time())


class MarketOrderRequest(BaseModel):
    """Market order request. Exactly one of {quantity, quote} must be provided."""

    model_config = ConfigDict(extra="ignore")  # allow unknown fields

    symbol: str = Field(..., description="e.g., BTCUSDT.BINANCE")
    side: Literal["BUY", "SELL"]
    quote: float | None = Field(None, gt=0, description="Quote currency amount (USDT).")
    quantity: float | None = Field(None, gt=0, description="Base asset quantity.")
    market: str | None = Field(
        None, description="Preferred market within venue (spot/futures/margin)."
    )
    venue: str | None = Field(None, description="Trading venue. Defaults to VENUE env var.")

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_exclusive(self) -> MarketOrderRequest:
        if (self.quantity is None) == (self.quote is None):
            raise MutuallyExclusiveOrderFieldError
        return self


class LimitOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., description="e.g., BTCUSDT.BINANCE")
    side: Literal["BUY", "SELL"]
    price: float = Field(..., gt=0, description="Limit price")
    timeInForce: Literal["IOC", "FOK", "GTC"] = Field("IOC")
    quote: float | None = Field(None, gt=0, description="Quote currency amount (USDT).")
    quantity: float | None = Field(None, gt=0, description="Base asset quantity.")
    market: str | None = Field(
        None, description="Preferred market within venue (spot/futures/margin)."
    )

    @model_validator(mode="after")
    def validate_exclusive(self) -> LimitOrderRequest:
        if (self.quantity is None) == (self.quote is None):
            raise MutuallyExclusiveOrderFieldError
        return self


def _record_venue_error(venue: str, exc: Exception) -> None:
    """Best-effort metric hook for venue-facing errors."""
    try:
        venue_label = (venue or VENUE).upper()
        error_label = "UNKNOWN"
        message = str(exc) or ""
        lowered = message.lower()
        if "authentication" in lowered:
            error_label = "AUTHENTICATION"
        elif "no_price" in lowered or "NO_PRICE" in message:
            error_label = "NO_PRICE"
        elif ":" in message:
            error_label = message.split(":", 1)[0].strip().upper().replace(" ", "_")
        elif message:
            error_label = message.strip().upper().replace(" ", "_")
        else:
            error_label = exc.__class__.__name__.upper()
        metrics.venue_errors.labels(venue=venue_label, error=error_label[:64]).inc()
    except Exception as exc:
        _log_suppressed("record venue error metrics", metric_exc)


@app.on_event("startup")
async def on_startup() -> None:
    async with startup_lock:
        _startup_logger.info("Startup sequence started (role=%s, venue=%s)", ROLE, VENUE)
        try:
            h = _config_hash()
            flags = {
                k: os.getenv(k)
                for k in [
                    "EVENT_BREAKOUT_ENABLED",
                    "EVENT_BREAKOUT_DRY_RUN",
                    "EVENT_BREAKOUT_METRICS",
                    "DEX_FEED_ENABLED",
                    "SCALP_MAKER_SHADOW",
                    "ALLOW_STOP_AMEND",
                    "AUTO_CUTBACK_ENABLED",
                    "RISK_PARITY_ENABLED",
                    "DEPEG_GUARD_ENABLED",
                    "FUNDING_GUARD_ENABLED",
                ]
                if os.getenv(k) is not None
            }
            _startup_logger.info("Config hash=%s flags=%s", h, flags)
        except Exception as exc:
            _log_suppressed("startup config hash logging", exc)
        # Start event bus early so other tasks can publish
        try:
            await initialize_event_bus()
            _startup_logger.info("Event bus initialized")
        except Exception as exc:
            _startup_logger.warning("Event bus init failed", exc_info=True)
        await router.initialize_balances()
        # Optional: seed starting cash for demo/test if no balances detected
        try:
            state = portfolio.state
            if state.cash is None or state.cash <= 0:
                seed = os.getenv("STARTING_CASH_USD") or os.getenv("ENGINE_STARTING_CASH_USD")
                if seed is not None:
                    val = float(seed)
                    if val > 0:
                        state.cash = val
                        state.equity = val
                        _startup_logger.info("Seeded starting cash of %s USD", val)
        except Exception as exc:
            _startup_logger.warning("Unable to seed starting cash: %s", exc, exc_info=True)
        # Initialize portfolio metrics
        state = portfolio.state
        metrics.reset_core_metrics()
        metrics.update_portfolio_gauges(
            state.cash, state.realized, state.unrealized, state.exposure
        )
        _startup_logger.info("Startup sequence completed")


async def _refresh_specs_periodically() -> None:
    """Background task to refresh venue specs daily."""
    import datetime
    import logging

    logging.getLogger().info("Starting venue specs refresh background task")
    while True:
        try:
            from engine.core import venue_specs_loader

            venue_specs_loader.refresh()
            global _last_specs_refresh
            _last_specs_refresh = time.time()
            # Update metric
            if hasattr(metrics, "REGISTRY"):
                metric = metrics.REGISTRY.get("last_specs_refresh_epoch")
                set_fn = getattr(metric, "set", None)
                if callable(set_fn):
                    set_fn(_last_specs_refresh)
            refreshed_at = datetime.datetime.utcfromtimestamp(_last_specs_refresh)
            logging.getLogger().info("Venue specs refreshed at %s", refreshed_at)
        except Exception as exc:
            logging.getLogger().exception("Spec refresh failed")
        await asyncio.sleep(86400)  # 24h


@app.on_event("startup")
async def _start_specs_refresh() -> None:
    """Start the background venue specs refresh task."""
    asyncio.create_task(_refresh_specs_periodically())
    _startup_logger.info("Scheduled venue specs refresh task")


@app.on_event("startup")
async def _start_param_bridge() -> None:
    """Bootstrap the ParamController bridge for dynamic strategy params."""
    global _PARAM_BRIDGE
    base_url = os.getenv("PARAM_CONTROLLER")
    if not base_url:
        return
    strategy_cfg = load_strategy_config()
    if not getattr(strategy_cfg, "hmm_enabled", False):
        return
    risk_cfg = load_risk_config()
    symbols = [
        s for s in (risk_cfg.trade_symbols or []) if s and s.strip().upper() not in {"*", "ALL"}
    ]
    if not symbols:
        symbols = ["BTCUSDT"]
    refresh = float(os.getenv("PARAM_REFRESH_SEC", "45"))
    client = bootstrap_param_client(base_url, refresh_interval=refresh)
    if client is None:
        return
    for sym in symbols:
        client.register_symbol("hmm", sym)
    await client.start()
    client.wire_feedback(BUS)
    _PARAM_BRIDGE = client
    _startup_logger.info("Param controller bridge started for %d symbols", len(symbols))


@app.on_event("shutdown")
async def _stop_param_bridge() -> None:
    client = get_param_client()
    if client:
        await client.stop()


@app.on_event("startup")
async def _start_model_watchdog() -> None:
    global _MODEL_WATCHER
    poll = float(os.getenv("MODEL_WATCH_INTERVAL_SEC", "5"))
    strategy_cfg = load_strategy_config()
    paths = []
    active_override = os.getenv("HMM_ACTIVE_MODEL")
    if active_override:
        paths.append(Path(active_override))
    paths.append(Path("engine/models/active_hmm_policy.pkl"))
    if getattr(strategy_cfg, "hmm_model_path", None):
        paths.append(Path(strategy_cfg.hmm_model_path))
    watcher = ModelPromotionWatcher(paths=paths, bus=BUS, poll_interval=poll)
    await watcher.start()
    _MODEL_WATCHER = watcher
    _startup_logger.info("Model promotion watcher armed (paths=%d)", len(paths))


@app.on_event("shutdown")
async def _stop_model_watchdog() -> None:
    global _MODEL_WATCHER
    if _MODEL_WATCHER:
        await _MODEL_WATCHER.stop()
        _MODEL_WATCHER = None


@app.on_event("startup")
async def _start_auto_topup_loop() -> None:
    if IS_EXPORTER or VENUE != "BINANCE":
        return
    if not AUTO_TOPUP_ENABLED:
        _AUTO_TOPUP_LOG.info("auto_topup: disabled; worker not started")
        return
    asyncio.create_task(auto_topup_worker(), name="auto-topup")


@app.on_event("startup")
async def _start_wallet_monitor() -> None:
    if IS_EXPORTER or VENUE != "BINANCE":
        return
    if not (settings.api_key and settings.api_secret):
        _WALLET_LOG.info("wallet monitor: credentials missing; not starting")
        return
    asyncio.create_task(wallet_balance_worker(), name="wallet-balance")


@app.on_event("startup")
async def _init_multi_venue_clients() -> None:
    """Initialize and register multi-venue exchange clients."""
    if IS_EXPORTER:
        return
    try:
        import os

        from engine.connectors.ibkr_client import IbkrClient

        # Only initialize IBKR if connection details are provided
        if os.getenv("IBKR_HOST"):
            ibkr_client = IbkrClient()
            set_exchange_client("IBKR", ibkr_client)
            _startup_logger.info("IBKR client initialized and registered")
    except ImportError:
        _startup_logger.warning(
            "IBKR client not available - ib-insync not installed", exc_info=True
        )
    except Exception as exc:
        _startup_logger.exception("IBKR client initialization failed")


@app.on_event("startup")
async def _start_reconciliation() -> None:
    """Start the order state reconciliation daemon."""
    try:
        from engine.core.reconcile_daemon import reconcile_loop

        asyncio.create_task(reconcile_loop())
        _startup_logger.info("Reconciliation daemon started")
    except ImportError:
        _startup_logger.warning("Reconciliation module not available", exc_info=True)
    except Exception as exc:
        _startup_logger.exception("Reconciliation daemon startup failed")


# Optional: start risk guardian and DEX feed when enabled via env
_GUARDIAN = None
_DEX_SNIPER = None
_DEX_WATCHER = None


@app.on_event("startup")
async def _start_guardian_and_feeds() -> None:
    if IS_EXPORTER:
        return

    # Risk event wiring
    async def _handle_risk_violation(evt: dict[str, Any]) -> None:
        if evt.get("action") == "PAUSE":
            RAILS.set_manual_trading_enabled(False)
            _startup_logger.critical("Trading PAUSED via EventBus: %s", evt.get("reason"))

    BUS.subscribe("risk.violation", _handle_risk_violation)

    # Risk guardian
    try:
        from engine.risk_guardian import RiskGuardian, load_guardian_config

        cfg = load_guardian_config()
        if cfg.enabled:
            global _GUARDIAN
            _GUARDIAN = RiskGuardian(cfg)
            await _GUARDIAN.start()
            _startup_logger.info("Risk guardian started")
            # Wire soft/critical handlers if bus is running
            try:
                from engine.handlers import risk_handlers

                BUS.subscribe(
                    "risk.cross_health_soft",
                    risk_handlers.on_cross_health_soft(router, cfg),
                )
                BUS.subscribe(
                    "risk.cross_health_critical",
                    risk_handlers.on_cross_health_critical(router, cfg),
                )
            except Exception as exc:
                _startup_logger.warning("Risk handlers did not wire", exc_info=True)
    except Exception as exc:
        _startup_logger.warning("Risk guardian failed to start", exc_info=True)

    # DEX feed loop
    try:
        import os

        if os.getenv("DEX_FEED_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.feeds.dexscreener import dexscreener_loop

            asyncio.create_task(dexscreener_loop(), name="dexscreener-feed")
            _startup_logger.info("DEX Screener feed started")
    except Exception as exc:
        _startup_logger.warning("DEX Screener feed failed to start", exc_info=True)

    # DEX sniper wiring
    try:
        from engine.dex import DexExecutor, DexState, load_dex_config
        from engine.dex.oracle import DexPriceOracle
        from engine.dex.router import DexRouter
        from engine.dex.wallet import DexWallet
        from engine.dex.watcher import DexWatcher
        from engine.handlers.dex_handlers import on_dex_candidate
        from engine.strategies.dex_sniper import DexSniper

        dex_cfg = load_dex_config()
        if dex_cfg.exec_enabled:
            global _DEX_SNIPER
            wallet = DexWallet(
                rpc_url=dex_cfg.rpc_url,
                chain_id=dex_cfg.chain_id,
                private_key=dex_cfg.wallet_private_key,
                max_gas_price_wei=dex_cfg.max_gas_price_wei,
            )
            dex_router = DexRouter(web3=wallet.w3, router_address=dex_cfg.router_address)
            state = DexState(dex_cfg.state_path)
            executor = DexExecutor(
                wallet=wallet,
                router=dex_router,
                stable_token=dex_cfg.stable_token,
                wrapped_native=dex_cfg.wrapped_native_token,
                gas_limit=dex_cfg.gas_limit,
                slippage_bps=dex_cfg.slippage_bps,
            )
            _DEX_SNIPER = DexSniper(dex_cfg, state, executor)
            BUS.subscribe("strategy.dex_candidate", on_dex_candidate(_DEX_SNIPER))
            _startup_logger.info(
                "DEX sniper wired (max_live=%s, tierA=%.2f, tierB=%.2f)",
                dex_cfg.max_live_positions,
                dex_cfg.size_tier_a,
                dex_cfg.size_tier_b,
            )
            if dex_cfg.watcher_enabled:
                global _DEX_WATCHER
                oracle = DexPriceOracle(transport=dex_cfg.price_oracle)
                _DEX_WATCHER = DexWatcher(dex_cfg, state, executor, oracle)
                _DEX_WATCHER.start()
                _startup_logger.info("DEX watcher loop started")
    except Exception as exc:
        _startup_logger.warning("DEX sniper wiring failed", exc_info=True)

    # Momentum breakout module
    try:
        from engine import strategy as _strategy_mod
        from engine.strategies.momentum_breakout import (
            MomentumBreakout,
            load_momentum_config,
        )

        momentum_cfg = load_momentum_config()
        if momentum_cfg.enabled:
            global _MOMENTUM_BREAKOUT
            scanner = getattr(_strategy_mod, "SYMBOL_SCANNER", None)
            _MOMENTUM_BREAKOUT = MomentumBreakout(router, RAILS, momentum_cfg, scanner=scanner)
            _MOMENTUM_BREAKOUT.start()
            _startup_logger.info(
                "Momentum breakout module started (notional=%.0f, interval=%.1fs)",
                momentum_cfg.notional_usd,
                momentum_cfg.interval_sec,
            )
    except Exception as exc:
        _startup_logger.warning("Momentum breakout wiring failed", exc_info=True)

    # Wire Event Breakout consumer (subscribe to strategy.event_breakout)
    try:
        if os.getenv("EVENT_BREAKOUT_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.strategies.event_breakout import EventBreakout

            bo = EventBreakout(router)
            # SIGHUP reload if denylist enabled
            if os.getenv("EVENT_BREAKOUT_DENYLIST_ENABLED", "").lower() in {
                "1",
                "true",
                "yes",
            }:
                try:
                    if hasattr(bo, "enable_sighup_reload"):
                        bo.enable_sighup_reload(bo.cfg.denylist_path)
                except Exception as exc:
                    _startup_logger.info("SIGHUP not supported for denylist reload")
            # Entropy-based auto-denylist wiring
            if os.getenv("ENTROPY_DENY_ENABLED", "").lower() in {"1", "true", "yes"}:
                try:
                    BUS.subscribe("event_bo.skip", bo.on_skip_entropy)
                    _startup_logger.info("Entropy deny wiring enabled")
                except Exception as exc:
                    _log_suppressed("engine guard", exc)
            BUS.subscribe("strategy.event_breakout", bo.on_event)
            _startup_logger.info("Event Breakout consumer wired")
    except Exception as exc:
        _startup_logger.warning("Event Breakout consumer failed to wire", exc_info=True)

    # Meme sentiment strategy wiring
    try:
        from engine.strategies.meme_coin_sentiment import (
            MemeCoinSentiment,
            load_meme_coin_config,
        )

        meme_cfg = load_meme_coin_config()
        global _MEME_SENTIMENT
        if meme_cfg.enabled:
            if _MEME_SENTIMENT is None:
                _MEME_SENTIMENT = MemeCoinSentiment(router, RAILS, rest_client, meme_cfg)
                BUS.subscribe("events.external_feed", _MEME_SENTIMENT.on_external_event)
                _startup_logger.info(
                    "Meme sentiment strategy enabled (risk_pct=%.2f%%, min_score=%.2f, lock=%.0fs)",
                    meme_cfg.per_trade_risk_pct * 100.0,
                    meme_cfg.min_social_score,
                    meme_cfg.trade_lock_sec,
                )
            else:
                _MEME_SENTIMENT.cfg = meme_cfg
                _MEME_SENTIMENT.rest_client = rest_client
                _startup_logger.info("Meme sentiment strategy configuration refreshed")
        elif _MEME_SENTIMENT is not None:
            try:
                BUS.unsubscribe("events.external_feed", _MEME_SENTIMENT.on_external_event)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            _MEME_SENTIMENT = None
            _startup_logger.info("Meme sentiment strategy disabled via configuration")
    except Exception as exc:
        _startup_logger.warning("Meme sentiment strategy wiring failed", exc_info=True)

    # Listing sniper wiring
    try:
        from engine.strategies.listing_sniper import (
            ListingSniper,
            load_listing_sniper_config,
        )

        listing_cfg = load_listing_sniper_config()
        if listing_cfg.enabled:
            global _LISTING_SNIPER
            if _LISTING_SNIPER is None:
                _LISTING_SNIPER = ListingSniper(router, RAILS, rest_client, listing_cfg)
                BUS.subscribe("events.external_feed", _LISTING_SNIPER.on_external_event)
                _startup_logger.info(
                    "Listing sniper enabled (risk_pct=%.2f%%, notional_min=%.1f, max=%.1f)",
                    listing_cfg.per_trade_risk_pct * 100.0,
                    listing_cfg.min_notional_usd,
                    listing_cfg.max_notional_usd,
                )
            else:
                _LISTING_SNIPER.cfg = listing_cfg
                _LISTING_SNIPER.rest_client = rest_client
                _startup_logger.info("Listing sniper configuration refreshed")
        elif _LISTING_SNIPER is not None:
            try:
                BUS.unsubscribe("events.external_feed", _LISTING_SNIPER.on_external_event)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            try:
                await _LISTING_SNIPER.shutdown()
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            _LISTING_SNIPER = None
            _startup_logger.info("Listing sniper disabled via configuration")
    except Exception as exc:
        _startup_logger.warning("Listing sniper wiring failed", exc_info=True)

    # Airdrop / promotion watcher wiring
    try:
        from engine.strategies.airdrop_promo import (
            AirdropPromoWatcher,
            load_airdrop_promo_config,
        )

        airdrop_cfg = load_airdrop_promo_config()
        global _AIRDROP_PROMO
        if airdrop_cfg.enabled:
            if _AIRDROP_PROMO is None:
                _AIRDROP_PROMO = AirdropPromoWatcher(router, RAILS, rest_client, airdrop_cfg)
                BUS.subscribe("events.external_feed", _AIRDROP_PROMO.on_external_event)
                _startup_logger.info(
                    "Airdrop promo watcher enabled (default_notional=%.1f, min_reward=%.1f)",
                    airdrop_cfg.default_notional_usd,
                    airdrop_cfg.min_expected_reward_usd,
                )
            else:
                _AIRDROP_PROMO.cfg = airdrop_cfg
                _AIRDROP_PROMO.rest_client = rest_client
                _startup_logger.info("Airdrop promo watcher configuration refreshed")
        elif _AIRDROP_PROMO is not None:
            try:
                BUS.unsubscribe("events.external_feed", _AIRDROP_PROMO.on_external_event)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            try:
                await _AIRDROP_PROMO.shutdown()
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            _AIRDROP_PROMO = None
            _startup_logger.info("Airdrop promo watcher disabled via configuration")
    except Exception as exc:
        _startup_logger.warning("Airdrop promo watcher wiring failed", exc_info=True)

    # Start Telegram digest (if enabled)
    try:
        if os.getenv("TELEGRAM_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.ops.digest import DigestJob
            from engine.telemetry.rollups import EventBOBuckets, EventBORollup
            from ops.notify.bridge import NotifyBridge
            from ops.notify.telegram import Telegram

            tg = Telegram(
                os.getenv("TELEGRAM_BOT_TOKEN", ""),
                os.getenv("TELEGRAM_CHAT_ID", ""),
                _startup_logger,
            )
            # Notify bridge (relay BUS notify.telegram)
            bridge_enabled = os.getenv("TELEGRAM_BRIDGE_ENABLED", "true").lower() in {
                "1",
                "true",
                "yes",
            }
            try:
                NotifyBridge(tg, BUS, _startup_logger, enabled=bridge_enabled)
                _startup_logger.info(
                    "Telegram notify bridge %s",
                    "enabled" if bridge_enabled else "disabled",
                )
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            # Health notifier (BUS -> Telegram) if enabled
            try:
                import time as _t

                from engine.ops.health_notify import HealthNotifier

                hcfg = {
                    "HEALTH_TG_ENABLED": os.getenv("HEALTH_TG_ENABLED", "true").lower()
                    in {"1", "true", "yes"},
                    "HEALTH_DEBOUNCE_SEC": int(float(os.getenv("HEALTH_DEBOUNCE_SEC", "10"))),
                }
                HealthNotifier(hcfg, BUS, tg, _startup_logger, _t, metrics)
                _startup_logger.info("Telegram health notifier wired")
            except Exception as exc:
                _startup_logger.warning("Health notifier wiring failed", exc_info=True)
            # Lightweight fills -> Telegram helper (until Alertmanager is in place)
            try:

                async def _on_fill_tele(evt: dict[str, Any]) -> None:
                    sym = (evt.get("symbol") or "").upper()
                    side = (evt.get("side") or "").upper()
                    px = float(evt.get("avg_price") or 0.0)
                    qty = float(evt.get("filled_qty") or 0.0)
                    if not sym or px <= 0 or qty <= 0:
                        return
                    BUS.fire(
                        "notify.telegram",
                        {"text": f"✅ Fill: *{sym}* {side} qty={qty:.6f} @ `{px}`"},
                    )

                BUS.subscribe("trade.fill", _on_fill_tele)
                _startup_logger.info("Telegram fill pings enabled")
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            roll = EventBORollup()
            # Optional 6h buckets
            buckets = EventBOBuckets(
                bucket_minutes=int(float(os.getenv("DIGEST_6H_BUCKET_MIN", "360"))),
                max_buckets=int(float(os.getenv("DIGEST_6H_MAX_BUCKETS", "4"))),
            )

            # Subscribe to event breakout rollup events
            def _subs(bus: Any, fn: Callable[[str, dict[str, Any]], None]) -> None:
                BUS.subscribe("event_bo.plan_dry", lambda data: fn("plans_dry", data))
                BUS.subscribe("event_bo.plan_live", lambda data: fn("plans_live", data))
                BUS.subscribe("event_bo.trade", lambda data: fn("trades", data))
                BUS.subscribe("event_bo.skip", lambda data: fn(f"skip_{data.get('reason')}", data))
                BUS.subscribe("event_bo.half", lambda data: fn("half_applied", data))
                BUS.subscribe("event_bo.trail", lambda data: fn("trail_update", data))

            _subs(BUS, lambda key, d: roll.inc(key, d.get("symbol")))
            _subs(BUS, lambda key, d: buckets.inc(key, d.get("symbol")))
            job = DigestJob(roll, tg, log=_startup_logger)
            job.buckets = buckets
            asyncio.create_task(job.run())
            _startup_logger.info("Telegram digest job started")
    except Exception as exc:
        _startup_logger.warning("Telegram digest failed to start", exc_info=True)

    # Guards: Depeg and Funding
    try:
        if os.getenv("DEPEG_GUARD_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.guards.depeg_guard import DepegGuard

            depeg = DepegGuard(router, bus=BUS, log=_startup_logger)

            async def _loop_depeg() -> None:
                while True:
                    try:
                        await depeg.tick()
                        from engine.metrics import risk_depeg_active

                        now = __import__("time").time()
                        val = 1 if now < depeg.safe_until else 0
                        try:
                            risk_depeg_active.set(val)
                        except Exception as exc:
                            _log_suppressed("engine guard", exc)
                    except Exception as exc:
                        _log_suppressed("engine guard", exc)
                    await asyncio.sleep(60)

            asyncio.create_task(_loop_depeg())
            _startup_logger.info("Depeg guard started")
    except Exception as exc:
        _startup_logger.warning("Depeg guard wiring failed", exc_info=True)

    try:
        if os.getenv("FUNDING_GUARD_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.guards.funding_guard import FundingGuard

            funding = FundingGuard(router, bus=BUS, log=_startup_logger)

            async def _loop_funding() -> None:
                while True:
                    try:
                        await funding.tick()
                    except Exception as exc:
                        _log_suppressed("engine guard", exc)
                    await asyncio.sleep(300)

            asyncio.create_task(_loop_funding())
            _startup_logger.info("Funding guard started")
    except Exception as exc:
        _startup_logger.warning("Funding guard wiring failed", exc_info=True)

    # Subscribe to model promotion events for hot-reload
    try:
        BUS.subscribe("model.promoted", strategy.policy_hmm.reload_model)
        _startup_logger.info("Subscribed to model.promoted event for hot-reload")
    except Exception as exc:
        _startup_logger.warning("Failed to subscribe to model.promoted", exc_info=True)

    # Auto cutback/mute overrides (symbol-level execution control)
    try:
        if os.getenv("AUTO_CUTBACK_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.execution.venue_overrides import VenueOverrides

            ov = VenueOverrides()
            # Listen to slippage samples and skip events
            BUS.subscribe(
                "event_bo.skip",
                lambda d: ov.record_skip(d.get("symbol", ""), str(d.get("reason", ""))),
            )
            BUS.subscribe(
                "exec.slippage",
                lambda d: ov.record_slippage_sample(d.get("symbol", ""), float(d.get("bps", 0.0))),
            )
            # attach to router for place_entry consult
            try:
                router._overrides = ov
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            _startup_logger.info("Auto cutback/mute overrides enabled")
    except Exception as exc:
        _startup_logger.warning("Auto cutback wiring failed", exc_info=True)


@app.post("/reconcile/manual")
async def manual_reconciliation() -> dict[str, Any]:
    """Trigger a manual reconciliation run."""
    try:
        from engine.core.reconcile_daemon import reconcile_once

        stats = await reconcile_once()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Manual reconciliation failed: {exc}") from exc
    else:
        return {"status": "completed", **stats}


# Startup restoration: load snapshot and best-effort reconcile
def _startup_load_snapshot_and_reconcile() -> None:
    # 1) Load prior snapshot (if present) so UI has immediate state
    snap = _store.load()
    if snap:
        _startup_logger.info("Loaded persisted portfolio snapshot (ts_ms=%s)", snap.get("ts_ms"))
        _boot_status["snapshot_loaded"] = True
        try:
            state = portfolio.state
            state.cash = float(snap.get("cash", state.cash))
            state.equity = float(snap.get("equity", state.equity))
            pnl = snap.get("pnl") or {}
            state.realized = float(pnl.get("realized", state.realized))
            state.unrealized = float(pnl.get("unrealized", state.unrealized))
            state.exposure = float(snap.get("exposure", state.exposure))
            state.positions.clear()
            for entry in snap.get("positions", []):
                try:
                    sym = (entry.get("symbol") or "").split(".")[0].upper()
                    qty = float(entry.get("qty_base", 0.0))
                    if qty == 0.0:
                        continue
                    pos = Position(symbol=sym)
                    pos.quantity = qty
                    pos.avg_price = float(entry.get("avg_price_quote", 0.0))
                    pos.last_price = float(entry.get("last_price_quote", pos.avg_price))
                    pos.upl = float(entry.get("unrealized_usd", 0.0))
                    pos.rpl = float(entry.get("realized_usd", 0.0))
                    state.positions[sym] = pos
                except Exception as exc:
                    _log_suppressed("snapshot position parse", exc)
                    continue
            try:
                _last_position_symbols.clear()
                _last_position_symbols.update(state.positions.keys())
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            metrics.update_portfolio_gauges(
                state.cash, state.realized, state.unrealized, state.exposure
            )
        except Exception as exc:
            _startup_logger.warning("Failed to hydrate portfolio from snapshot", exc_info=True)
    else:
        _startup_logger.info("No persisted portfolio snapshot found; starting fresh")
    # 2) Best-effort reconcile to catch up with missed fills (only if credentials exist)
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if api_key and api_secret and api_key not in {"__REQUIRED__", "__PLACEHOLDER__"}:
        try:
            post_reconcile()  # same logic; small universe should be fast
        except Exception as exc:
            # Non-fatal — engine can still serve, UI can trigger /reconcile manually
            _startup_logger.warning("Initial reconcile on startup failed", exc_info=True)
    else:
        _startup_logger.warning(
            "Skipping startup reconcile because Binance API credentials are not configured."
        )
    # 3) Start strategy scheduler if enabled
    try:
        strategy.start_scheduler()
        _startup_logger.info("Strategy scheduler started")
    except Exception as exc:
        _startup_logger.warning("Strategy scheduler failed to start", exc_info=True)


# Run extra startup restoration after startup event
# Initialize strategy hooks
momentum_strategy = None


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _MOMENTUM_BREAKOUT, _LISTING_SNIPER, _MEME_SENTIMENT, _AIRDROP_PROMO, _market_data_logger
    if _market_data_logger is not None:
        try:
            _market_data_logger.stop()
            _startup_logger.info("Market data logger stopped")
        except Exception as exc:
            _startup_logger.debug("Market data logger shutdown encountered issues", exc_info=True)
        _market_data_logger = None
    try:
        if _MOMENTUM_BREAKOUT is not None:
            await _MOMENTUM_BREAKOUT.stop()
            _MOMENTUM_BREAKOUT = None
    except Exception as exc:
        _startup_logger.warning("Momentum breakout shutdown encountered errors", exc_info=True)
    try:
        if _LISTING_SNIPER is not None:
            await _LISTING_SNIPER.shutdown()
    except Exception as exc:
        _startup_logger.warning("Listing sniper shutdown failed", exc_info=True)
    try:
        if _MEME_SENTIMENT is not None:
            from engine.core.event_bus import BUS

            try:
                BUS.unsubscribe("events.external_feed", _MEME_SENTIMENT.on_external_event)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            _MEME_SENTIMENT = None
    except Exception as exc:
        _startup_logger.warning("Meme sentiment shutdown failed", exc_info=True)
    try:
        if _AIRDROP_PROMO is not None:
            from engine.core.event_bus import BUS

            try:
                BUS.unsubscribe("events.external_feed", _AIRDROP_PROMO.on_external_event)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
            try:
                await _AIRDROP_PROMO.shutdown()
            except Exception as exc:
                _startup_logger.warning("Airdrop promo watcher shutdown failed", exc_info=True)
            _AIRDROP_PROMO = None
    except Exception as exc:
        _startup_logger.warning("Airdrop promo shutdown encountered errors", exc_info=True)
    try:
        from engine.core.signal_queue import SIGNAL_QUEUE

        await SIGNAL_QUEUE.stop()
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    await rest_client.close()


@app.post("/orders/market", response_model=None)
async def submit_market_order(
    req: MarketOrderRequest, request: Request
) -> JSONResponse | dict[str, Any]:
    # Idempotency check
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        cached = CACHE.get(idem_key)
        if cached:
            return JSONResponse(content=cached, status_code=200)

    ok, err = RAILS.check_order(
        symbol=req.symbol,
        side=req.side,
        quote=req.quote,
        quantity=req.quantity,
        market=(req.market.lower() if isinstance(req.market, str) else req.market),
    )
    if not ok:
        metrics.orders_rejected.inc()
        status = 403 if err.get("error") in {"TRADING_DISABLED", "SYMBOL_NOT_ALLOWED"} else 400
        # Publish risk rejection event
        await publish_risk_event(
            "rejected",
            {
                "symbol": req.symbol,
                "side": req.side,
                "quote": req.quote,
                "quantity": req.quantity,
                "reason": err.get("error", "UNKNOWN_RISK_VIOLATION"),
                "timestamp": time.time(),
            },
        )
        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

    # Register pending order to block concurrent execution
    # Estimate notional: use quote if available, else quantity (assumed 1.0 for lock presence check if price unknown)
    est_notional = req.quote if req.quote else (req.quantity or 1.0)
    RAILS.register_pending(req.symbol, float(est_notional))

    try:
        # Apply venue-suffix to symbol if not present, defaulting to request venue or env VENUE
        venue = (req.venue or "").upper() or VENUE
        if "." not in req.symbol:
            req.symbol = f"{req.symbol}.{venue}"

        # ——— Existing execution path (left intact) ———
        if req.quote is not None:
            result = await router.market_quote(
                req.symbol,
                req.side,
                req.quote,
                market=(req.market.lower() if isinstance(req.market, str) else None),
            )
        else:
            result = await router.market_quantity(
                req.symbol,
                req.side,
                req.quantity or 0.0,
                market=(req.market.lower() if isinstance(req.market, str) else None),
            )

        # Store order persistently
        order_id = result.get("id") or str(int(time.time() * 1000))
        if "id" not in result:
            result["id"] = order_id
        if store is not None:
            try:
                _persist_logger.info("Persisting order %s in SQLite", order_id)
                store.insert_order(
                    {
                        "id": order_id,
                        "venue": venue.lower(),
                        "symbol": (result.get("symbol") or req.symbol).rsplit(".", 1)[0],
                        "side": req.side,
                        "qty": req.quantity or req.quote,
                        "price": result.get("price") or result.get("avg_fill_price"),
                        "status": "PLACED",
                        "ts_accept": int(time.time() * 1000),
                        "ts_update": int(time.time() * 1000),
                    }
                )
                _persist_logger.debug("Order %s stored successfully", order_id)
            except Exception as exc:
                _persist_logger.exception("Failed to persist order %s", order_id)

        metrics.orders_submitted.inc()

        # Terminal status counters now increment in Portfolio.apply_fill();
        # additional venue statuses (canceled/expired) can be recorded by
        # reconciliation or explicit cancel flows.

        # Apply immediate fill to internal portfolio state (best-effort)
        try:
            raw_symbol = result.get("symbol") or req.symbol
            qty_base = float(result.get("filled_qty_base") or 0.0)
            px = float(result.get("avg_fill_price") or 0.0)
            fee_usd = float(result.get("fee_usd") or 0.0)
            venue_hint = (result.get("venue") or venue).upper()
            market_hint = result.get("market") or (
                req.market.lower() if isinstance(req.market, str) else None
            )
            if raw_symbol and "." not in raw_symbol and venue_hint:
                full_symbol = f"{raw_symbol}.{venue_hint}"
            else:
                full_symbol = raw_symbol
            if qty_base > 0 and px > 0 and full_symbol:
                portfolio.apply_fill(
                    symbol=full_symbol,
                    side=req.side,
                    quantity=qty_base,
                    price=px,
                    fee_usd=fee_usd,
                    venue=venue_hint,
                    market=market_hint,
                )
                # Update gauges after applying the fill
                state = portfolio.state
                metrics.update_portfolio_gauges(
                    state.cash, state.realized, state.unrealized, state.exposure
                )
                # Persist snapshot
                _store.save(state.snapshot())
        except Exception as exc:
            # Non-fatal; reconcile daemon or manual /reconcile can catch up
            _log_suppressed("portfolio fill persistence", exc)

        resp = {
            "status": "submitted",
            "order": result,
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        append_jsonl("orders.jsonl", resp)
        if idem_key:
            CACHE.set(idem_key, resp)
        return resp

    except Exception as exc:
        metrics.orders_rejected.inc()
        _record_venue_error(venue, exc)
        # Surface Binance error payloads for easier debugging
        try:
            if isinstance(exc, _httpx.HTTPStatusError) and exc.response is not None:
                status = exc.response.status_code
                body = exc.response.text
                raise HTTPException(status_code=status, detail=f"Binance error: {body}") from exc
        except Exception as exc:
            _log_suppressed("engine guard", payload_exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    finally:
        RAILS.clear_pending(req.symbol, float(est_notional))


@app.post("/orders/limit", response_model=None)
async def submit_limit_order(
    req: LimitOrderRequest, request: Request
) -> JSONResponse | dict[str, Any]:
    # Idempotency check
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        cached = CACHE.get(idem_key)
        if cached:
            return JSONResponse(content=cached, status_code=200)

    ok, err = RAILS.check_order(
        symbol=req.symbol,
        side=req.side,
        quote=req.quote,
        quantity=req.quantity,
        market=(req.market.lower() if isinstance(req.market, str) else req.market),
    )
    if not ok:
        metrics.orders_rejected.inc()
        status = 403 if err.get("error") in {"TRADING_DISABLED", "SYMBOL_NOT_ALLOWED"} else 400
        await publish_risk_event(
            "rejected",
            {
                "symbol": req.symbol,
                "side": req.side,
                "quote": req.quote,
                "quantity": req.quantity,
                "reason": err.get("error", "UNKNOWN_RISK_VIOLATION"),
                "timestamp": time.time(),
            },
        )
        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

    # Register pending order
    est_notional = req.quote if req.quote else (req.quantity or 1.0)
    RAILS.register_pending(req.symbol, float(est_notional))

    try:
        venue = req.symbol.split(".")[1].upper() if "." in req.symbol else VENUE
        if "." not in req.symbol:
            req.symbol = f"{req.symbol}.{venue}"

        market_hint = req.market.lower() if isinstance(req.market, str) else None
        if req.quote is not None:
            result = await router.limit_quote(
                req.symbol,
                req.side,
                req.quote,
                req.price,
                req.timeInForce,
                market=market_hint,
            )
        else:
            result = await router.limit_quantity(
                req.symbol,
                req.side,
                req.quantity or 0.0,
                req.price,
                req.timeInForce,
                market=market_hint,
            )

        # Store order persistently
        order_id = result.get("id") or str(int(time.time() * 1000))
        if store is not None:
            try:
                _persist_logger.info("Persisting order %s in SQLite", order_id)
                store.insert_order(
                    {
                        "id": order_id,
                        "venue": venue.lower(),
                        "symbol": (result.get("symbol") or req.symbol).rsplit(".", 1)[0],
                        "side": req.side,
                        "qty": req.quantity or req.quote,
                        "price": req.price,
                        "status": "PLACED",
                        "ts_accept": int(time.time() * 1000),
                        "ts_update": int(time.time() * 1000),
                    }
                )
                _persist_logger.debug("Order %s stored successfully", order_id)
            except Exception as exc:
                _persist_logger.exception("Failed to persist order %s", order_id)

        metrics.orders_submitted.inc()

        # Apply immediate fill (best-effort)
        try:
            raw_symbol = result.get("symbol") or req.symbol
            qty_base = float(result.get("filled_qty_base") or 0.0)
            px = float(result.get("avg_fill_price") or 0.0)
            fee_usd = float(result.get("fee_usd") or 0.0)
            venue_hint = (result.get("venue") or venue).upper()
            market_hint = result.get("market") or (
                req.market.lower() if isinstance(req.market, str) else None
            )
            if raw_symbol and "." not in raw_symbol and venue_hint:
                full_symbol = f"{raw_symbol}.{venue_hint}"
            else:
                full_symbol = raw_symbol
            if qty_base > 0 and px > 0 and full_symbol:
                portfolio.apply_fill(
                    symbol=full_symbol,
                    side=req.side,
                    quantity=qty_base,
                    price=px,
                    fee_usd=fee_usd,
                    venue=venue_hint,
                    market=market_hint,
                )
                st = portfolio.state
                metrics.update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
                _store.save(st.snapshot())
        except Exception as exc:
            _log_suppressed("engine guard", exc)

        resp = {
            "status": "submitted",
            "order": result,
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        append_jsonl("orders.jsonl", resp)
        if idem_key:
            CACHE.set(idem_key, resp)
        return resp

    except Exception as exc:
        metrics.orders_rejected.inc()
        _record_venue_error(venue, exc)
        try:
            if isinstance(exc, _httpx.HTTPStatusError) and exc.response is not None:
                status = exc.response.status_code
                body = exc.response.text
                raise HTTPException(status_code=status, detail=f"Binance error: {body}") from exc
        except Exception as exc:
            _log_suppressed("engine guard", payload_exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    finally:
        RAILS.clear_pending(req.symbol, float(est_notional))


@app.get("/symbol_info")
async def symbol_info(symbol: str) -> dict[str, Any]:
    """Return live venue filters for a symbol (min_notional, step size, etc.).

    Accepts symbols with or without venue suffix (e.g., BTCUSDT or BTCUSDT.BINANCE).
    """
    try:
        clean = symbol.split(".")[0].upper()
        filt = await rest_client.exchange_filter(clean)
        return {
            "symbol": clean,
            "step_size": filt.step_size,
            "min_qty": filt.min_qty,
            "min_notional": filt.min_notional,
            "max_notional": filt.max_notional,
            "tick_size": getattr(filt, "tick_size", 0.0),
            "is_futures": settings.is_futures,  # Add mode indicator
        }
    except _httpx.HTTPStatusError as exc:
        third_party = "undefined"
        if exc.response is not None and hasattr(exc.response, "url"):
            third_party = str(exc.response.url)
        base_used = settings.api_base or "no_base"
        mode_info = f"mode={settings.mode}, is_futures={settings.is_futures}"
        detail_msg = (
            "symbol_info failed: "
            f"{exc} ({mode_info}, base_url={base_used}, url_attempted={third_party})"
        )
        raise HTTPException(status_code=400, detail=detail_msg) from exc
    except Exception as exc:
        base_used = settings.api_base or "no_base"
        mode_info = f"mode={settings.mode}, is_futures={settings.is_futures}"
        detail_msg = (
            "symbol_info failed: "
            f"{exc} ({mode_info}, base_url={base_used}, url_attempted=undefined)"
        )
        raise HTTPException(status_code=400, detail=detail_msg) from exc


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> dict[str, Any]:
    """Return order data from JSONL audit log."""
    path = Path("engine/logs/orders.jsonl")
    if not path.exists():
        raise HTTPException(status_code=404, detail="No orders logged yet")
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if str(rec.get("order", {}).get("id")) == order_id:
                return rec
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")


@app.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    """
    Fast read via router if available, else return last snapshot.
    """
    persisted_snapshot: dict[str, Any] | None = None
    try:
        snap = router.portfolio_snapshot()
        needs_overlay = (
            ("equity_usd" not in snap)
            or ("cash_usd" not in snap)
            or not snap.get("positions")
            or not snap.get("pnl")
        )
        if needs_overlay:
            persisted_snapshot = _store.load()
            if persisted_snapshot:
                if "cash_usd" not in snap and persisted_snapshot.get("cash_usd") is not None:
                    snap["cash_usd"] = _coerce_float(persisted_snapshot.get("cash_usd"))
                if "equity_usd" not in snap and persisted_snapshot.get("equity_usd") is not None:
                    snap["equity_usd"] = _coerce_float(persisted_snapshot.get("equity_usd"))
                if not snap.get("positions"):
                    snap["positions"] = list(persisted_snapshot.get("positions", []))
                if not snap.get("pnl") and persisted_snapshot.get("pnl"):
                    snap["pnl"] = dict(persisted_snapshot.get("pnl") or {})
                if "ts_ms" not in snap and persisted_snapshot.get("ts_ms") is not None:
                    snap["ts_ms"] = persisted_snapshot.get("ts_ms")
    except Exception as exc:
        snap = _store.load()
        persisted_snapshot = snap
        if not snap:
            raise HTTPException(status_code=404, detail="No portfolio available") from exc
        snap.setdefault("equity_usd", snap.get("equity"))
        if "equity" not in snap and snap.get("cash_usd") is not None and snap.get("pnl"):
            pnl = snap.get("pnl") or {}
            snap["equity_usd"] = _coerce_float(snap.get("cash_usd"), 0.0) + _coerce_float(
                pnl.get("unrealized", 0.0), 0.0
            )
        return snap
    # Ensure UI gets USDT-normalized exposure per-position and dust-hidden hint
    try:
        prices = await last_prices()
        dust = risk_cfg.dust_threshold_usd
        positions = snap.get("positions", [])
        for p in positions:
            base = p.get("symbol", "").split(".")[0]
            base = base if base.endswith(QUOTE_CCY) else f"{base}{QUOTE_CCY}"
            last = prices.get(base) or p.get("last_price_quote")
            qty = float(p.get("qty_base", 0.0))
            p["last_price_quote"] = last
            p["unrealized_usd"] = float(p.get("unrealized_usd", 0.0))  # keep if already computed
            p["value_usd"] = (qty * float(last)) if (last is not None) else 0.0
            p["is_dust"] = abs(p["value_usd"]) < dust
            # Also update internal portfolio marks so unrealized PnL tracks market
            try:
                if last is not None:
                    portfolio.update_price(base, float(last))
            except Exception as exc:
                _log_suppressed("engine guard", exc)
        snap["quote_ccy"] = QUOTE_CCY
        snap["positions"] = positions
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    # Refresh engine metrics from latest snapshot so external scrapers see updated values
    try:
        state = portfolio.state
        # Start with current state values; override below for futures
        metrics.update_portfolio_gauges(
            state.cash, state.realized, state.unrealized, state.exposure
        )

        if settings.is_futures:
            # Compute unrealized PnL directly from the latest futures snapshot
            # and accumulate across ALL open positions.
            try:
                snap2 = await router.get_account_snapshot()
            except Exception as exc:
                _persist_logger.warning("Futures snapshot fetch failed", exc_info=True)
                snap2 = None

            positions2 = snap2.get("positions", []) if isinstance(snap2, dict) else []
            total_unreal = 0.0
            metric_unreal = cast(Any, metrics.REGISTRY.get("pnl_unrealized_symbol"))
            for pp in positions2:
                try:
                    qty = float(pp.get("positionAmt", 0) or 0)
                    if abs(qty) <= 0.0:
                        continue
                    sym = str(pp.get("symbol", ""))
                    # Prefer venue-provided unrealizedProfit for mark-based PnL
                    upnl = float(pp.get("unrealizedProfit", 0.0) or 0.0)
                    total_unreal += upnl
                    if metric_unreal is not None and sym:
                        metric_unreal.labels(symbol=sym).set(upnl)
                except Exception as exc:
                    _log_suppressed("futures pnl gauge update", exc)
                    continue
            # market_value_usd := total unrealized (not Σ qty*price) for linear futures
            metrics.set_core_metric("market_value_usd", total_unreal)
            # Pull wallet cash directly from the venue snapshot for futures
            cash = 0.0
            if isinstance(snap2, dict):
                try:
                    cash = float(
                        snap2.get("totalWalletBalance") or snap2.get("walletBalance") or 0.0
                    )
                except Exception as exc:
                    cash = float(getattr(state, "cash", 0.0) or 0.0)
            else:
                cash = float(getattr(state, "cash", 0.0) or 0.0)

            # Sync in-process portfolio cash so subsequent calls are consistent
            try:
                portfolio.state.cash = cash
            except Exception as exc:
                _log_suppressed("engine guard", exc)

            # Update gauges using live cash + unrealized (venue truth)
            metrics.update_portfolio_gauges(cash, state.realized, total_unreal, state.exposure)
            try:
                metrics.set_core_metric("cash_usd", cash)
                metrics.set_core_metric("equity_usd", cash + total_unreal)
                # Margin figures (if present on snapshot)
                if isinstance(snap2, dict):
                    try:
                        init_m = float(snap2.get("totalInitialMargin", 0.0))
                        maint_m = float(snap2.get("totalMaintMargin", 0.0))
                        avail = float(
                            snap2.get("availableBalance", snap2.get("maxWithdrawAmount", 0.0))
                        )
                        metrics.set_core_metric("initial_margin_usd", init_m)
                        metrics.set_core_metric("maint_margin_usd", maint_m)
                        metrics.set_core_metric("available_usd", avail)
                    except Exception as exc:
                        _log_suppressed("engine guard", exc)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
        else:
            # Spot: signed market value = sum(qty * last)
            try:
                mv = sum(pos.quantity * pos.last_price for pos in state.positions.values())
                metrics.set_core_metric("market_value_usd", mv)
                # Per-symbol unrealized for invariants derived from in-process state
                metric_unreal = cast(Any, metrics.REGISTRY.get("pnl_unrealized_symbol"))
                if metric_unreal is not None:
                    for pos in state.positions.values():
                        metric_unreal.labels(symbol=pos.symbol).set(pos.upl)
            except Exception as exc:
                _log_suppressed("engine guard", exc)
        # Record mark time for auditability - always set, even when no positions
        try:
            metrics.set_core_metric("mark_time_epoch", time.time())
        except Exception as exc:
            _log_suppressed("engine guard", exc)
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    try:
        state = portfolio.state
        snap.setdefault("cash_usd", _coerce_float(getattr(state, "cash", 0.0)))
        snap.setdefault("equity_usd", _coerce_float(getattr(state, "equity", 0.0)))
        pnl = snap.get("pnl") or {}
        pnl.setdefault("realized", _coerce_float(getattr(state, "realized", 0.0)))
        pnl.setdefault("unrealized", _coerce_float(getattr(state, "unrealized", 0.0)))
        snap["pnl"] = pnl
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    if "cash_usd" not in snap or "equity_usd" not in snap:
        fallback = persisted_snapshot or _store.load() or {}
        if "cash_usd" not in snap and fallback.get("cash_usd") is not None:
            snap["cash_usd"] = _coerce_float(fallback.get("cash_usd"))
        if "equity_usd" not in snap:
            if fallback.get("equity_usd") is not None:
                snap["equity_usd"] = _coerce_float(fallback.get("equity_usd"))
            elif snap.get("equity") is not None:
                snap["equity_usd"] = _coerce_float(snap.get("equity"))
            else:
                pnl = snap.get("pnl") or {}
                snap["equity_usd"] = _coerce_float(snap.get("cash_usd"), 0.0) + _coerce_float(
                    pnl.get("unrealized", 0.0), 0.0
                )
    return snap


@app.get("/account_snapshot")
async def account_snapshot(force: bool = False) -> dict[str, Any]:
    """
    Return account snapshot. If force=1, pull a fresh snapshot from the venue
    and update router cache + snapshot_loaded flag immediately.
    """
    snap = await (router.fetch_account_snapshot() if force else router.get_account_snapshot())

    try:
        router.snapshot_loaded = True
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    state = portfolio.state
    try:
        metrics.update_portfolio_gauges(
            state.cash, state.realized, state.unrealized, state.exposure
        )
        metrics.set_core_metric("equity_usd", float(state.equity))
        metrics.set_core_metric("available_usd", float(snap.get("availableBalance", state.cash)))
        metrics.set_core_metric("mark_time_epoch", time.time())
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    if store is not None:
        snapshot_ts = int(time.time() * 1000)
        try:
            for sym, position in state.positions.items():
                base_sym = sym.split(".")[0]
                store.upsert_position(
                    VENUE.lower(),
                    base_sym,
                    position.quantity,
                    position.avg_price,
                    snapshot_ts,
                )
            cash_val = float(getattr(state, "cash", 0.0) or 0.0)
            unreal_val = float(getattr(state, "unrealized", 0.0) or 0.0)
            equity_val = float(
                getattr(state, "equity", cash_val + unreal_val) or (cash_val + unreal_val)
            )
            if isinstance(snap, dict):
                cash_val = float(snap.get("cash_usd", cash_val) or cash_val)
                pnl_section = snap.get("pnl") or {}
                unreal_val = float(pnl_section.get("unrealized", unreal_val) or unreal_val)
                equity_candidate = snap.get("equity_usd") or snap.get("equity")
                if equity_candidate is not None:
                    equity_val = float(equity_candidate)
                elif not equity_val:
                    equity_val = cash_val + unreal_val
            store.insert_equity(VENUE.lower(), equity_val, cash_val, unreal_val, snapshot_ts)
        except Exception as exc:
            _persist_logger.exception(
                "Failed to persist account snapshot for venue %s", VENUE.lower()
            )
    else:
        _persist_logger.debug("SQLite store unavailable; skipping account snapshot persistence")

    current_symbols: set[str] = set()
    for sym, position in state.positions.items():
        key = sym.split(".")[0]
        current_symbols.add(key)
        metrics.set_core_symbol_metric("position_amt", symbol=key, value=float(position.quantity))
        metrics.set_core_symbol_metric("entry_price", symbol=key, value=float(position.avg_price))
        metrics.set_core_symbol_metric("unrealized_profit", symbol=key, value=float(position.upl))
        if position.last_price:
            metrics.set_core_symbol_metric(
                "mark_price", symbol=key, value=float(position.last_price)
            )
    try:
        stale = _last_position_symbols - current_symbols
        for sym in stale:
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
        _last_position_symbols.clear()
        _last_position_symbols.update(current_symbols)
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    try:
        _store.save(state.snapshot())
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    return snap


@app.post("/account_snapshot/refresh")
async def account_snapshot_refresh() -> dict[str, Any]:
    """Force-refresh the venue snapshot and update gauges."""
    return await account_snapshot(force=True)


@app.post("/reconcile")
def post_reconcile() -> dict[str, Any]:
    """
    Fetch fills since last snapshot and apply. Runs in the request thread for simplicity;
    you can move to background if reconciliation might be slow.
    """
    # Symbols: prefer TRADE_SYMBOLS allowlist; fallback to router universe
    symbols = risk_cfg.trade_symbols or []
    if not symbols:
        try:
            symbols = router.trade_symbols()  # EXPECTED: provide in router
        except Exception as exc:
            symbols = []
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols configured for reconciliation")

    try:
        snap = reconcile_since_snapshot(
            portfolio=router.portfolio_service(),  # EXPECTED: provide in router
            client=router.exchange_client(),  # EXPECTED: provide in router
            symbols=[s if s.endswith("USDT") else f"{s}USDT" for s in symbols],
        )
        _boot_status["reconciled"] = True
        global _last_reconcile_ts
        _last_reconcile_ts = time.time()
        metrics.reconcile_lag_seconds.set(0.0)
        return {
            "status": "ok",
            "applied_snapshot_ts_ms": snap.get("ts_ms"),
            "equity": snap.get("equity_usd"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reconcile failed: {exc}") from exc


@app.on_event("startup")
async def _bootstrap_snapshot_state() -> None:
    """Restore snapshot + reconcile in background to avoid blocking server startup."""
    try:
        await asyncio.to_thread(_startup_load_snapshot_and_reconcile)
    except Exception as exc:
        _startup_logger.warning("Snapshot bootstrap failed", exc_info=True)


@app.get("/status")
async def status() -> dict[str, Any]:
    """Return engine status."""
    return {
        "status": "ok",
        "timestamp": time.time(),
        "uptime": time.time() - _START_TIME if "_START_TIME" in globals() else 0,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        snap = _store.load() or {}
    except Exception as exc:
        snap = {}
    lag = max(0.0, time.time() - _last_reconcile_ts) if _last_reconcile_ts else None
    if lag is not None:
        metrics.reconcile_lag_seconds.set(lag)
    # Update snapshot_loaded gauge for alerting - derive truth from router state
    snap_ok = bool(getattr(router, "snapshot_loaded", False))
    try:
        snapshot_metric = cast(Any, metrics.REGISTRY.get("snapshot_loaded"))
        if snapshot_metric is not None:
            snapshot_metric.set(1 if snap_ok else 0)
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    # Venue-specific labels for health endpoint
    # Binance-only health metadata (other venues removed during purge)
    equity_source = "fapi/v2/account.totalMarginBalance"
    upnl_source = "positionRisk.sum(unRealizedProfit)"
    price_source = "mark_price/premiumIndex"
    wallet_source = "fapi/v2/account.totalWalletBalance"

    # Include symbols if unrestricted
    from engine.config import load_risk_config

    risk_cfg = load_risk_config()
    symbols = None
    if not risk_cfg.trade_symbols:
        try:
            from engine.universe import configured_universe

            symbols = configured_universe()
        except Exception as exc:
            _log_suppressed("engine guard", exc)

    return {
        "engine": "ok",
        "mode": settings.mode,
        "api_base": settings.api_base,  # Updated to show active base URL
        "trading_enabled": settings.trading_enabled,
        "last_snapshot_error": getattr(router, "last_snapshot_error", None),
        "snapshot_loaded": snap_ok,  # UPDATED: accurate from router state
        "reconciled": getattr(router, "reconciled", False),
        "equity": snap.get("equity_usd"),
        "pnl_unrealized": (snap.get("pnl") or {}).get("unrealized"),
        "quote_ccy": QUOTE_CCY,
        "reconcile_lag_seconds": lag,
        "symbols": symbols,
        "price_source": price_source,
        "basis_source": "positionRisk" if settings.is_futures else "in_memory",
        "positions_tracked": len(_basis_cache),
        "symbols_universe": len(_price_map) if _price_map else None,
        "equity_source": equity_source,
        "upnl_source": upnl_source,
        "wallet_source": wallet_source,
    }


@app.get("/universe")
def get_universe() -> dict[str, Any]:
    """Return configured trading symbols in BASEQUOTE (no venue suffix)."""
    return {"symbols": configured_universe(), "quote_ccy": QUOTE_CCY}


@app.get("/prices")
async def get_prices() -> dict[str, Any]:
    """Return last trade/mark prices for current universe."""
    return {"prices": await last_prices(), "ts": time.time(), "quote_ccy": QUOTE_CCY}


@app.get("/price")
async def get_price(
    symbol: str = Query(..., description="Symbol e.g. BTCUSDT or BTCUSDT.BINANCE"),
) -> dict[str, Any]:
    """Return the latest price for a single symbol."""
    normalized = norm_symbol(symbol)
    prices = await last_prices()
    price = prices.get(normalized)

    if price is None:
        venue_symbol = symbol if "." in symbol else f"{normalized}.{VENUE}"
        try:
            price = await router.get_last_price(venue_symbol)
        except Exception as exc:
            price = None

    if price is None:
        raise HTTPException(status_code=404, detail=f"price unavailable for {symbol}")

    return {
        "symbol": normalized,
        "price": float(price),
        "quote_ccy": QUOTE_CCY,
        "ts": time.time(),
    }


# ============================================================================
# Aggregate Endpoints for Frontend Dashboard
# ============================================================================

# Global state for session baseline
_DYNAMIC_BASELINE: float | None = None

@app.get("/aggregate/portfolio")
async def get_aggregate_portfolio() -> dict[str, Any]:
    """Aggregate portfolio summary for dashboard."""
    global _DYNAMIC_BASELINE
    state = portfolio.state
    equity = state.equity or 0
    cash = state.cash or 0
    
    # Determine baseline:
    # 1. Use explicit env var if set (e.g. for paper trading / fixed starts)
    # 2. Else use first-seen non-zero equity (session PnL)
    # 3. Fallback to equity (0 PnL) or 10000 if equity is 0
    env_baseline = os.getenv("BASELINE_EQUITY_USD")
    if env_baseline:
        baseline = float(env_baseline)
    else:
        if _DYNAMIC_BASELINE is None and equity > 0:
            _DYNAMIC_BASELINE = equity
        baseline = _DYNAMIC_BASELINE if _DYNAMIC_BASELINE else (equity if equity > 0 else 10000.0)

    gain = equity - baseline
    return_pct = (gain / baseline) if baseline > 0 else 0
    
    return {
        "equity_usd": equity,
        "cash_usd": cash,
        "gain_usd": gain,
        "return_pct": return_pct,
        "baseline_equity_usd": baseline,
        "last_refresh_epoch": time.time()
    }


@app.get("/aggregate/exposure")
async def get_aggregate_exposure() -> dict[str, Any]:
    """Aggregate exposure across all positions."""
    state = portfolio.state
    by_symbol: dict[str, dict[str, Any]] = {}
    total_exposure = 0.0
    venues_seen = set()
    
    for symbol, pos in state.positions.items():
        qty = abs(pos.quantity or 0)
        last_price = pos.last_price or 0
        exposure = qty * last_price
        total_exposure += exposure
        
        venue = symbol.split(".")[-1] if "." in symbol else "BINANCE"
        venues_seen.add(venue)
        
        by_symbol[symbol] = {
            "qty_base": pos.quantity or 0,
            "last_price_usd": last_price,
            "exposure_usd": exposure
        }
    
    return {
        "totals": {
            "exposure_usd": total_exposure,
            "count": len(state.positions),
            "venues": len(venues_seen)
        },
        "by_symbol": by_symbol
    }


@app.get("/aggregate/pnl")
async def get_aggregate_pnl() -> dict[str, Any]:
    """Aggregate realized and unrealized PnL by symbol."""
    state = portfolio.state
    realized: dict[str, float] = {}
    unrealized: dict[str, float] = {}
    
    for symbol, pos in state.positions.items():
        realized[symbol] = pos.rpl or 0
        unrealized[symbol] = pos.upl or 0
    
    return {
        "realized": realized,
        "unrealized": unrealized,
        "total_realized": state.realized or 0,
        "total_unrealized": state.unrealized or 0
    }


@app.get("/strategies")
async def get_strategies() -> dict[str, Any]:
    """List active strategies with their status."""
    strategies_data = []
    
    # Default empty params schema
    default_params_schema = {"fields": []}
    
    # Get strategy modules status
    try:
        from engine import strategy as strat_mod
        
        if hasattr(strat_mod, 'TREND_MODULE') and strat_mod.TREND_MODULE:
            strategies_data.append({
                "id": "trend_follow",
                "name": "Trend Follow",
                "kind": "trend",
                "status": "running" if getattr(strat_mod.TREND_MODULE, 'enabled', False) else "stopped",
                "symbols": getattr(strat_mod.TREND_CFG, 'symbols', []) if strat_mod.TREND_CFG else [],
                "paramsSchema": default_params_schema,
                "params": {},
            })
        
        if hasattr(strat_mod, 'SCALP_MODULE') and strat_mod.SCALP_MODULE:
            strategies_data.append({
                "id": "scalp",
                "name": "Scalp Strategy",
                "kind": "scalp",
                "status": "running" if getattr(strat_mod.SCALP_MODULE, 'enabled', False) else "stopped",
                "symbols": getattr(strat_mod.SCALP_CFG, 'symbols', []) if strat_mod.SCALP_CFG else [],
                "paramsSchema": default_params_schema,
                "params": {},
            })
        
        if hasattr(strat_mod, 'MOMENTUM_RT_MODULE') and strat_mod.MOMENTUM_RT_MODULE:
            strategies_data.append({
                "id": "momentum_rt",
                "name": "Momentum RT",
                "kind": "momentum",
                "status": "running" if getattr(strat_mod.MOMENTUM_RT_MODULE, 'enabled', False) else "stopped",
                "symbols": getattr(strat_mod.MOMENTUM_RT_CFG, 'symbols', []) if strat_mod.MOMENTUM_RT_CFG else [],
                "paramsSchema": default_params_schema,
                "params": {},
            })

        if hasattr(strat_mod, 'LIQU_MODULE') and strat_mod.LIQU_MODULE:
            liqu_schema = {
                "fields": [
                    {"key": "dry_run", "type": "boolean", "label": "Dry Run"},
                    {"key": "grid_steps", "type": "number", "label": "Grid Steps", "min": 1, "max": 10, "step": 1},
                    {"key": "size_usd", "type": "number", "label": "Size (USD)", "min": 10, "max": 10000},
                    {"key": "stop_loss_pct", "type": "number", "label": "Stop Loss %", "step": 0.01},
                    {"key": "take_profit_pct", "type": "number", "label": "Take Profit %", "step": 0.01},
                ]
            }
            # Populate basic params from config
            l_cfg = getattr(strat_mod, 'LIQU_CFG', None)
            l_params = {}
            if l_cfg:
                l_params = {
                    "dry_run": l_cfg.dry_run,
                    "grid_steps": len(l_cfg.grid_steps) if l_cfg.grid_steps else 3,
                    "size_usd": l_cfg.size_usd,
                    "stop_loss_pct": l_cfg.stop_loss_pct,
                    "take_profit_pct": l_cfg.take_profit_pct,
                }

            strategies_data.append({
                "id": "liquidation_sniper",
                "name": "Liquidation Sniper",
                "kind": "liquidation",
                "status": "running" if getattr(strat_mod.LIQU_MODULE, 'enabled', False) else "stopped",
                "symbols": ["ALL"], # Global watcher
                "paramsSchema": liqu_schema,
                "params": l_params,
            })
        
        # HMM/Ensemble
        s_cfg = getattr(strat_mod, 'S_CFG', None)
        if s_cfg:
            if getattr(s_cfg, 'hmm_enabled', False):
                strategies_data.append({
                    "id": "hmm_ensemble",
                    "name": "HMM Ensemble",
                    "kind": "hmm",
                    "status": "running" if getattr(s_cfg, 'enabled', False) else "stopped",
                    "symbols": getattr(s_cfg, 'symbols', []),
                    "paramsSchema": default_params_schema,
                    "params": {},
                    "metrics": getattr(strat_mod.policy_hmm, 'get_regime', lambda s: {})(getattr(s_cfg, 'symbols', ['BTCUSDT'])[0]) or {},
                    "performance": {
                        "realized_pnl": 0.0,
                        "unrealized_pnl": 0.0,
                        "pnl": 0.0,
                        "sharpe": 0.0,
                        "drawdown": 0.0,
                        "winRate": 0.0,
                        "equitySeries": []
                    }
                })
    except Exception as exc:
        pass
    
    return {
        "data": strategies_data,
        "page": {"nextCursor": None, "prevCursor": None, "limit": 50}
    }



@app.get("/trades/recent")
async def get_recent_trades(limit: int = 100) -> dict[str, Any]:
    """Get recent trades from SQLite store."""
    trades = []
    
    if store is not None:
        try:
            rows = store.get_recent_orders(limit=limit)
            for row in rows:
                trades.append({
                    "id": row.get("id", ""),
                    "symbol": row.get("symbol", ""),
                    "side": row.get("side", ""),
                    "quantity": row.get("qty", 0),
                    "price": row.get("price", 0),
                    "pnl": row.get("pnl", 0),
                    "timestamp": row.get("ts_accept", 0),
                    "strategyId": row.get("strategy", "unknown"),
                    "venueId": row.get("venue", "binance")
                })
        except Exception as exc:
            pass
    
    return {
        "data": trades,
        "page": {"nextCursor": None, "prevCursor": None, "limit": limit}
    }


@app.get("/trades/stats")
async def get_trade_stats() -> dict[str, Any]:
    """Get computed trade statistics: win rate, sharpe, max drawdown."""
    stats = {"win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "total_trades": 0, "returns": []}
    
    if store is not None:
        try:
            computed = store.compute_trade_stats()
            stats["win_rate"] = computed.get("win_rate", 0.0)
            stats["total_trades"] = computed.get("total_trades", 0)
            stats["max_drawdown"] = computed.get("max_drawdown", 0.0)
            
            # Compute Sharpe ratio from returns if available
            returns = computed.get("returns", [])
            if returns and len(returns) >= 5:
                import statistics
                mean_ret = statistics.mean(returns)
                std_ret = statistics.stdev(returns) if len(returns) > 1 else 1.0
                # Annualize assuming daily trades
                if std_ret > 0:
                    stats["sharpe"] = round((mean_ret / std_ret) * (252 ** 0.5), 2)
                stats["returns"] = returns[-50:]  # Last 50 returns for charting
        except Exception as exc:
            pass
    
    return stats


@app.get("/alerts")
async def get_alerts(limit: int = 50) -> dict[str, Any]:
    """Get recent system alerts."""
    alerts = []
    
    # Pull from alert daemon if available
    try:
        daemon = alert_daemon.get_instance()
        if daemon:
            alerts = daemon.get_recent_alerts(limit)
    except Exception as exc:
        pass
    
    return {
        "data": alerts,
        "page": {"nextCursor": None, "prevCursor": None, "limit": limit}
    }


@app.get("/orders/open")
async def get_open_orders() -> dict[str, Any]:
    """Get currently open orders."""
    orders = []
    
    # Get from router's pending orders if available
    try:
        pending = getattr(router, '_pending_orders', {})
        for order_id, order in pending.items():
            orders.append({
                "id": order_id,
                "symbol": order.get("symbol", ""),
                "side": order.get("side", ""),
                "type": order.get("type", "MARKET"),
                "qty": order.get("qty", 0),
                "filled": order.get("filled", 0),
                "price": order.get("price", 0),
                "status": order.get("status", "PENDING"),
                "createdAt": order.get("ts", 0)
            })
    except Exception as exc:
        pass
    
    return {
        "data": orders,
        "page": {"nextCursor": None, "prevCursor": None, "limit": 100}
    }



@app.post("/strategy/promote")
async def promote_strategy(request: Request) -> dict[str, Any]:
    """Hot-swap to a new strategy model at runtime."""
    import os

    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail='JSON body required: {"model_tag": "<tag>"}'
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload (expected object)")
    tag = (data or {}).get("model_tag")
    if not tag:
        raise HTTPException(status_code=400, detail="model_tag required")

    # Update environment and global model tag
    global MODEL_TAG
    MODEL_TAG = tag
    os.environ["MODEL_TAG"] = tag

    # Optionally notify strategy layer to reload model
    try:
        if hasattr(strategy, "reload_model"):
            await strategy.reload_model(tag)
    except AttributeError:
        pass  # Strategy layer doesn't support hot reload, that's ok
    except Exception as exc:
        # Surface reload errors clearly to caller
        raise HTTPException(status_code=500, detail=f"reload_model failed: {exc}") from exc

    return {"message": f"Strategy switched to {tag}", "model_tag": tag}


@app.get("/stream")
async def sse_stream() -> StreamingResponse:
    """Server-Sent Events endpoint for real-time engine updates."""

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for live UI updates."""
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        handlers = {}  # Keep references to prevent garbage collection

        def queue_event(topic: str, data: dict[str, Any]) -> None:
            queue.put_nowait((topic, data))

        # Subscribe to key event topics
        topics = [
            "order.submitted",
            "order.filled",
            "order.closed",
            "risk.rejected",
            "metrics.update",
            "strategy.promoted",
            "reconcile.completed",
        ]

        for topic in topics:
            handlers[topic] = lambda data, topic=topic: queue_event(topic, data)
            BUS.subscribe(topic, handlers[topic])

        try:
            while True:
                topic, data = await queue.get()
                # Format as SSE (Server-Sent Events)
                yield f"event: {topic}\ndata: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            # Unsubscribe when connection closes
            for topic, handler in handlers.items():
                BUS.unsubscribe(topic, handler)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.on_event("startup")
async def _start_external_feeds() -> None:
    """Launch external data feed connectors described in YAML config."""
    if IS_EXPORTER:
        return
    try:
        from engine.feeds.external_connectors import spawn_external_feeds_from_config

        started = await spawn_external_feeds_from_config()
        if started:
            _startup_logger.info("External feed connectors started: %s", ", ".join(started))
    except Exception as exc:
        _startup_logger.warning("External feed connectors failed to start", exc_info=True)


@app.on_event("startup")
async def _start_event_bus() -> None:
    """Initialize the real-time event bus."""
    if IS_EXPORTER:
        return
    try:
        await initialize_event_bus()
        _startup_logger.info("Event bus started")
        SIGNAL_QUEUE.start(BUS)
        _startup_logger.info("Signal priority queue dispatcher online")
    except Exception as exc:
        _startup_logger.exception("Event bus startup failed")


@app.on_event("startup")
async def _start_alerting() -> None:
    """Initialize the real-time alerting system."""
    if IS_EXPORTER:
        return
    try:
        await alert_daemon.initialize_alerting()
        _startup_logger.info("Alerting system started")
    except Exception as exc:
        _startup_logger.exception("Alerting startup failed")


@app.on_event("startup")
async def _start_governance() -> None:
    """Initialize the autonomous governance system - the final layer!"""
    if IS_EXPORTER:
        return
    try:
        from ops import governance_daemon

        await governance_daemon.initialize_governance()
        _startup_logger.info("Autonomous governance activated")
    except Exception as exc:
        _startup_logger.exception("Governance startup failed")


@app.on_event("startup")
async def _start_bracket_governor() -> None:
    if IS_EXPORTER:
        return
    try:
        if os.getenv("BRACKET_GOVERNOR_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
        }:
            BracketGovernor(router, BUS, _startup_logger).wire()
    except Exception as exc:
        _startup_logger.warning("Bracket governor wiring failed", exc_info=True)


@app.on_event("startup")
async def _start_stop_validator() -> None:
    global _stop_validator
    if IS_EXPORTER:
        return
    enabled = os.getenv("STOP_VALIDATOR_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    if not enabled:
        return
    cfg = {
        "STOP_VALIDATOR_ENABLED": enabled,
        "STOP_VALIDATOR_REPAIR": os.getenv("STOP_VALIDATOR_REPAIR", "true").lower()
        in {"1", "true", "yes"},
        "STOP_VALIDATOR_GRACE_SEC": float(os.getenv("STOP_VALIDATOR_GRACE_SEC", "2")),
        "STOP_VALIDATOR_INTERVAL_SEC": float(os.getenv("STOP_VALIDATOR_INTERVAL_SEC", "5")),
        "STOPVAL_NOTIFY_ENABLED": os.getenv("STOPVAL_NOTIFY_ENABLED", "false").lower()
        in {"1", "true", "yes"},
        "STOPVAL_NOTIFY_DEBOUNCE_SEC": float(os.getenv("STOPVAL_NOTIFY_DEBOUNCE_SEC", "60")),
    }
    try:
        md = _MDAdapter(router)
        _stop_validator = StopValidator(
            cfg, router, md, log=_startup_logger, metrics=metrics, bus=BUS
        )
        asyncio.create_task(_stop_validator.run())
        _startup_logger.info("Stop Validator started (repair=%s)", cfg["STOP_VALIDATOR_REPAIR"])
    except Exception as exc:
        _startup_logger.warning("Stop Validator startup failed", exc_info=True)


@app.on_event("startup")
async def _subscribe_governance_hooks() -> None:
    """React to governance actions by hot-reloading risk rails."""
    if IS_EXPORTER:
        return

    async def _on_governance_action(_data: dict) -> None:
        # Governance mutated runtime env vars; reflect into risk rails config
        pass

    try:
        RAILS.cfg = load_risk_config()
        metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
        try:
            metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
        except Exception as exc:
            _log_suppressed("engine guard", exc)
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    try:
        BUS.subscribe("governance.action", _on_governance_action)
    except Exception as exc:
        _log_suppressed("engine guard", exc)


_user_stream: BinanceUserStream | None = None

@app.on_event("startup")
async def _start_user_stream() -> None:
    """Start the Binance User Data Stream for real-time telemetry."""
    global _user_stream
    _app_logger.info(f"Starting User Stream check. IS_EXPORTER={IS_EXPORTER} KEY_LEN={len(settings.api_key) if settings.api_key else 0}")
    if IS_EXPORTER:
        return
    
    
    _app_logger.info(f"DEBUG: Starting User Stream check. IS_EXPORTER={IS_EXPORTER} KEY_LEN={len(settings.api_key) if settings.api_key else 0}")
    if not (settings.api_key and settings.api_secret):
        _app_logger.warning("User Stream skipped: missing API credentials")
        return

    async def on_account_update(data: dict) -> None:
        try:
            balances = {}
            # data['a']['B'] is list of balances
            # 'wb' = Wallet Balance
            for bal in data.get("a", {}).get("B", []):
                asset = bal.get("a")
                try:
                    balances[asset] = float(bal.get("wb", 0.0))
                except (ValueError, TypeError):
                    pass
            if balances:
                portfolio.sync_wallet(balances)
        except Exception as e:
            _app_logger.error(f"UserStream account update error: {e}")

    async def on_order_update(data: dict) -> None:
        try:
            o = data.get("o", {})
            status = o.get("X")
            if status in ("FILLED", "PARTIALLY_FILLED"):
                symbol = o.get("s")
                side = o.get("S")
                price = float(o.get("L", 0.0)) # Last filled price
                qty = float(o.get("l", 0.0)) # Last filled qty
                fee = float(o.get("n", 0.0)) # Commission
                fee_asset = o.get("N")
                
                # Simple fee estimation (assume USDT or ignore for now if not)
                fee_usd = fee if fee_asset == "USDT" else 0.0 
                
                portfolio.apply_fill(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    price=price,
                    fee_usd=fee_usd,
                    venue="BINANCE",
                    market="futures" # Assuming futures stream
                )
        except Exception as e:
            _app_logger.error(f"UserStream order update error: {e}")

    _user_stream = BinanceUserStream(
        on_account_update=on_account_update,
        on_order_update=on_order_update
    )
    asyncio.create_task(_user_stream.run())


_market_stream: BinanceMarketStream | None = None

@app.on_event("startup")
async def _start_param_client() -> None:
    """Start the Dynamic Parameter Controller Client & Reinforcement Learning Feedback Loop."""
    if IS_EXPORTER:
        return
    
    # [Dynamic Params & RL]
    try:
        # settings.ops_url should be like "http://ops:8000"
        if getattr(settings, "ops_url", None):
            p_client = bootstrap_param_client(settings.ops_url)
            if p_client:
                # Wire RL feedback (Bus -> ParamClient -> Ops)
                p_client.wire_feedback(BUS)
                await p_client.start()
                _app_logger.info("[ParamClient] Started & RL Feedback Wired")
            else:
                _app_logger.warning("[ParamClient] Failed to bootstrap (client is None)")
        else:
             _app_logger.info("[ParamClient] Skipped (OPS_URL not set)")
    except Exception as exc:
        _app_logger.warning("[ParamClient] Wiring failed: %s", exc)


async def _handle_universe_update(evt: dict[str, Any]) -> None:
    """Handle dynamic universe updates from SymbolScanner."""
    symbols = evt.get("symbols")
    if not symbols or not isinstance(symbols, list):
        return
        
    global _market_stream
    if _market_stream:
        _app_logger.info(f"[Universe] Updating subscription to {len(symbols)} symbols: {symbols[:3]}...")
        _market_stream.subscribe(symbols)
    
    # Update RiskRails allowlist so strategies can execute on these new symbols
    if hasattr(strategy, "RAILS") and strategy.RAILS:
        try:
            # RAILS.cfg is a frozen dataclass, so we replace it
            strategy.RAILS.cfg = replace(strategy.RAILS.cfg, trade_symbols=symbols)
            _app_logger.info(f"[Risk] Updated allowed trade_symbols: {len(symbols)} symbols")
        except Exception as exc:
            _app_logger.warning("Failed to update RiskRails allowlist: %s", exc)


@app.on_event("startup")
async def _start_market_stream() -> None:
    """Start the Binance Public Market Data Stream."""
    global _market_stream
    if IS_EXPORTER or VENUE != "BINANCE":
        return

    # [Dynamic Universe]
    try:
        BUS.subscribe("universe.update", _handle_universe_update)
    except Exception as exc:
        _app_logger.warning("Failed to subscribe to universe.update: %s", exc)

    # Gather all trading symbols
    symbols = configured_universe()
    if not symbols:
        # Fallback if universe not ready
        symbols = (os.getenv("TRADE_SYMBOLS") or "BTCUSDT,ETHUSDT").split(",")
        symbols = [s.strip() for s in symbols if s.strip()]

    async def on_market_event(data: dict) -> None:
        if _market_data_dispatcher:
            _market_data_dispatcher.handle_stream_event(data)
        
        # Update system telemetry (Price/Heartbeat)
        if data.get("type") == "trade":
            sym = data.get("symbol")
            price = data.get("price")
            ts = data.get("ts")
            if sym and price is not None:
                # _binance_on_mark updates metrics and triggers strategy ticks
                await _binance_on_mark(sym, sym, price, ts or time.time())
    
    MARKET_STREAM = BinanceMarketStream(symbols, on_event=on_market_event)
    _market_stream = MARKET_STREAM
    
    # Start the watchdog to update subscriptions dynamically
    async def _scanner_watchdog():
        if not SYMBOL_SCANNER:
            return
        
        logging.getLogger("engine.app").info("[Watchdog] Started dynamic symbol subscription watchdog")
        while True:
            await asyncio.sleep(30)
            try:
                # Get current target universe
                current = SYMBOL_SCANNER.get_selected()
                if current and _market_stream:
                    # BinanceMarketStream.subscribe handles diffing and reconnection automatically
                    _market_stream.subscribe(current)
            except Exception as e:
                logging.getLogger("engine.app").warning(f"[Watchdog] check failed: {e}")

    asyncio.create_task(_scanner_watchdog())
    asyncio.create_task(_market_stream.run())


@app.on_event("startup")
async def _start_telemetry_watchdog() -> None:
    """Monitor telemetry latency and alert if stale."""
    if IS_EXPORTER:
        return

    startup_ts = time.time()

    async def watchdog() -> None:
        while True:
            await asyncio.sleep(10)
            if _user_stream:
                lag = time.time() - _user_stream.last_event_ts
                # Grace period: 5 min after startup before alerting
                if time.time() - startup_ts < 300:
                    continue
                # 360s threshold (allows 5-minute keep-alive + buffer)
                if lag > 360:
                    _app_logger.error(f"CRITICAL: Telemetry Stale! Lag: {lag:.1f}s")
                    RAILS.set_circuit_breaker(True, f"Telemetry Lag {lag:.1f}s")
                    try:
                        await BUS.publish("alert.telemetry", {"type": "TELEMETRY_DISCONNECTED", "lag": lag})
                    except:
                        pass
                else:
                    # Reset if recovered
                    RAILS.set_circuit_breaker(False)

    asyncio.create_task(watchdog())


@app.on_event("startup")
async def _start_venue_monitor() -> None:
    """Start periodic venue health telemetry (Heartbeat for UI)."""
    if IS_EXPORTER or VENUE != "BINANCE":
        return

    async def _monitor_loop() -> None:
        _app_logger.info("[VenueMonitor] Started venue health telemetry")
        while True:
            try:
                # Check _market_stream connectivity
                connected = False
                latency = 50 # Default dummy latency
                
                if _market_stream:
                    # Proxy check: if _ws is set, we are connected
                    ws = getattr(_market_stream, "_ws", None)
                    if ws is not None:
                         # websockets 10.x+ has `open` property or we check state
                         if hasattr(ws, "open"):
                             connected = ws.open
                         else:
                             # Fallback for older versions or other libs
                             connected = not getattr(ws, "closed", True)
                
                # Emit venue.health (Single update)
                payload = {
                     "name": "BINANCE",
                     "status": "ok" if connected else "down",
                     "latency_ms": latency,
                     "connected": connected,
                     "ts": time.time()
                }
                await BROADCASTER.broadcast({
                    "type": "venue.health",
                    "data": payload
                })
                
                # Emit venues list (Heatmap/Dashboard)
                await BROADCASTER.broadcast({
                    "type": "venues",
                    "data": [{
                        "id": "BINANCE",
                        "name": "BINANCE",
                        "status": "ok" if connected else "down",
                        "latency_ms": latency,
                        "cnt": 1
                    }]
                })
            except Exception:
                pass
            await asyncio.sleep(2.0) # 2s freq for responsive UI

    asyncio.create_task(_monitor_loop(), name="venue-monitor")


@app.on_event("startup")
async def _start_fee_manager() -> None:
    """Start BNB auto-topup daemon for fee discounts."""
    if IS_EXPORTER:
        return

    try:
        from engine.ops.fee_manager import FeeManager, load_fee_manager_config

        config = load_fee_manager_config()
        if not config.enabled:
            _app_logger.info("[FeeManager] Disabled via config")
            return

        manager = FeeManager(portfolio, router, config=config)
        asyncio.create_task(manager.run())
        _app_logger.info("[FeeManager] Started")
    except Exception as exc:
        _app_logger.warning("[FeeManager] Failed to start: %s", exc)


@app.on_event("startup")
async def _start_watchdog() -> None:
    """Start engine health watchdog for self-healing."""
    if IS_EXPORTER:
        return

    try:
        from engine.ops.watchdog import get_watchdog

        watchdog = get_watchdog()
        watchdog.start()
        _app_logger.info("[Watchdog] Self-healing watchdog started")
    except Exception as exc:
        _app_logger.warning("[Watchdog] Failed to start: %s", exc)



async def _refresh_binance_futures_snapshot() -> None:
    """Single refresh tick for Binance futures accounts."""
    global _price_map, _basis_cache, _snapshot_counter

    try:
        # Heartbeat for watchdog
        try:
            from engine.ops.watchdog import get_watchdog
            get_watchdog().heartbeat()
        except Exception as exc:
            pass
        _refresh_logger.debug("refresh tick")
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    try:
        price_data = await rest_client.bulk_premium_index()
        if price_data:
            now_ts = time.time()
            new_map: dict[str, float] = {}
            for sym, payload in price_data.items():
                raw_px = payload
                if isinstance(payload, dict):
                    raw_px = payload.get("markPrice") or payload.get("price") or 0.0
                try:
                    px = float(raw_px or 0.0)
                except Exception as exc:
                    px = 0.0
                if px <= 0.0:
                    continue
                new_map[sym] = px
                try:
                    metrics.MARK_PRICE.labels(symbol=sym, venue="binance").set(px)
                except Exception as exc:
                    _log_suppressed("engine guard", exc)
                try:
                    await _maybe_emit_strategy_tick(sym, px, ts=now_ts, source="rest_snapshot", stream="rest")
                except Exception as exc:
                    pass
            if new_map:
                _price_map = new_map
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    try:
        acc_data = await rest_client.account()
    except Exception as exc:
        acc_data = {}
    if acc_data:
        try:
            wallet = float(acc_data.get("totalWalletBalance", 0.0))
            upnl = float(acc_data.get("totalUnrealizedProfit", 0.0))
            equity = float(acc_data.get("totalMarginBalance", 0.0))
        except Exception as exc:
            wallet = upnl = equity = 0.0

        metrics.set_core_metric("cash_usd", wallet)
        metrics.set_core_metric("equity_usd", equity)
        metrics.set_core_metric("market_value_usd", upnl)

        try:
            init_m = float(acc_data.get("totalInitialMargin", 0.0))
            maint_m = float(acc_data.get("totalMaintMargin", 0.0))
            avail = float(acc_data.get("availableBalance", acc_data.get("maxWithdrawAmount", 0.0)))
            metrics.set_core_metric("initial_margin_usd", init_m)
            metrics.set_core_metric("maint_margin_usd", maint_m)
            metrics.set_core_metric("available_usd", avail)
        except Exception as exc:
            _log_suppressed("engine guard", exc)

    try:
        pos_data = await rest_client.position_risk()
    except Exception as exc:
        pos_data = []
    pos_data = [p for p in pos_data if float(p.get("positionAmt", 0.0)) != 0.0]

    is_hedge = False
    try:
        is_hedge = await rest_client.hedge_mode()
    except Exception as exc:
        is_hedge = False

    if is_hedge:
        legs = [p for p in pos_data if p.get("positionSide") in ("LONG", "SHORT")]
    else:
        legs = [p for p in pos_data if p.get("positionSide", "BOTH") == "BOTH"]

    if legs:
        try:
            upnl_total = sum(float(p.get("unRealizedProfit", 0.0)) for p in legs)
            metrics.set_core_metric("market_value_usd", upnl_total)
        except Exception as exc:
            _log_suppressed("engine guard", exc)

    current_symbols: set[str] = set()
    by_symbol: dict[str, dict[str, float]] = {}
    for p in pos_data:
        sym = p.get("symbol", "")
        if not sym:
            continue
        entry = float(p.get("entryPrice", 0.0) or 0.0)
        amt = float(p.get("positionAmt", 0.0) or 0.0)
        upnl_sym = float(p.get("unRealizedProfit", 0.0) or 0.0)
        agg = by_symbol.setdefault(sym, {"amt": 0.0, "entry": 0.0, "upnl": 0.0})
        agg["amt"] += amt
        if entry and amt:
            try:
                weight = abs(amt)
                agg["entry"] = (
                    agg.get("entry", 0.0) * abs(agg.get("amt", 0.0)) + entry * weight
                ) / max(1e-9, abs(agg.get("amt", 0.0)) + weight)
            except Exception as exc:
                agg["entry"] = entry or agg.get("entry", 0.0)
        agg["upnl"] += upnl_sym

    for sym, agg in by_symbol.items():
        if agg.get("amt", 0.0) == 0.0:
            continue
        current_symbols.add(sym)
        _basis_cache[sym] = {
            "entry_price": float(agg.get("entry", 0.0)),
            "position_amt": float(agg.get("amt", 0.0)),
            "last_sync_epoch": time.time(),
        }
        try:
            metrics.set_core_symbol_metric(
                "position_amt", symbol=sym, value=float(agg.get("amt", 0.0))
            )
            metrics.set_core_symbol_metric(
                "entry_price", symbol=sym, value=float(agg.get("entry", 0.0))
            )
            metrics.set_core_symbol_metric(
                "unrealized_profit", symbol=sym, value=float(agg.get("upnl", 0.0))
            )
            mark = 0.0
            if isinstance(_price_map, dict):
                try:
                    raw_mark = _price_map.get(sym, 0.0)
                    if isinstance(raw_mark, dict):
                        mark = float(raw_mark.get("markPrice", 0.0) or 0.0)
                    else:
                        mark = float(raw_mark or 0.0)
                except Exception as exc:
                    mark = 0.0
            if mark:
                metrics.set_core_symbol_metric("mark_price", symbol=sym, value=mark)
                try:
                    metrics.MARK_PRICE.labels(symbol=sym, venue="binance").set(mark)
                except Exception as exc:
                    _log_suppressed("engine guard", exc)
        except Exception as exc:
            _log_suppressed("engine guard", exc)

    try:
        stale = _last_position_symbols - current_symbols
        for sym in stale:
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
        _last_position_symbols.clear()
        _last_position_symbols.update(current_symbols)
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    now_ts = time.time()
    metrics.set_core_metric("mark_time_epoch", now_ts)
    metrics.set_core_metric("metrics_heartbeat", now_ts)
    try:
        metrics.engine_component_uptime_seconds.labels(component=ROLE).set(
            now_ts - _ENGINE_START_TS
        )
    except ValueError:
        pass
    _snapshot_counter += 1
    metrics.set_core_metric("snapshot_id", _snapshot_counter)


async def _refresh_binance_spot_snapshot() -> None:
    """Single refresh tick tailored for Binance spot accounts."""
    global _price_map, _basis_cache, _snapshot_counter

    symbol_filter: set[str] = set()
    try:
        raw_symbols = await asyncio.to_thread(configured_universe)
        symbol_filter = {s.split(".")[0].upper() for s in raw_symbols}
    except Exception as exc:
        symbol_filter = set()

    try:
        base = (settings.spot_base or settings.api_base or "").rstrip(
            "/"
        ) or "https://api.binance.com"
        async with _httpx.AsyncClient(base_url=base, timeout=settings.timeout) as client:
            resp = await client.get("/api/v3/ticker/price")
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        payload = None

    if isinstance(payload, list):
        new_map: dict[str, float] = {}
        for item in payload:
            sym = str(item.get("symbol", "")).upper()
            if not sym:
                continue
            if symbol_filter and sym not in symbol_filter:
                continue
            try:
                px = float(item.get("price", 0.0))
            except Exception as exc:
                _log_suppressed("ticker price parse", exc)
                continue
            if px > 0:
                _price_map[sym] = px
                try:
                    await _maybe_emit_strategy_tick(sym, px, source="rest_snapshot", stream="rest")
                except Exception as exc:
                    pass
        if new_map:
            _price_map = new_map
            for sym, px in new_map.items():
                try:
                    metrics.MARK_PRICE.labels(symbol=sym, venue="binance").set(px)
                except Exception as exc:
                    _log_suppressed("mark price gauge update", exc)
                    continue

    try:
        account = await rest_client.account_snapshot()
    except Exception as exc:
        account = {}

    balances = account.get("balances") if isinstance(account, dict) else None
    wallet = 0.0
    if isinstance(balances, list):
        for bal in balances:
            asset = (bal.get("asset") or "").upper()
            if asset == QUOTE_CCY:
                try:
                    free = float(bal.get("free", 0.0))
                    locked = float(bal.get("locked", 0.0))
                except Exception as exc:
                    free = locked = 0.0
                wallet = free + locked
                break

    state = portfolio.state
    try:
        state.cash = wallet
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    unreal = float(getattr(state, "unrealized", 0.0) or 0.0)
    equity = wallet + unreal
    try:
        state.equity = equity
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    metrics.set_core_metric("cash_usd", wallet)
    metrics.set_core_metric("available_usd", wallet)
    metrics.set_core_metric("market_value_usd", unreal)
    metrics.set_core_metric("equity_usd", equity)

    now_ts = time.time()
    current_symbols: set[str] = set()
    for sym, position in state.positions.items():
        base_sym = sym.split(".")[0].upper()
        qty = float(getattr(position, "quantity", 0.0) or 0.0)
        if qty == 0.0:
            continue
        current_symbols.add(base_sym)
        _basis_cache[base_sym] = {
            "entry_price": float(getattr(position, "avg_price", 0.0) or 0.0),
            "position_amt": qty,
            "last_sync_epoch": now_ts,
        }
        try:
            metrics.set_core_symbol_metric("position_amt", symbol=base_sym, value=qty)
            metrics.set_core_symbol_metric(
                "entry_price",
                symbol=base_sym,
                value=float(getattr(position, "avg_price", 0.0) or 0.0),
            )
            metrics.set_core_symbol_metric(
                "unrealized_profit",
                symbol=base_sym,
                value=float(getattr(position, "upl", 0.0) or 0.0),
            )
            mark = 0.0
            if isinstance(_price_map, dict):
                try:
                    raw_mark = _price_map.get(base_sym, 0.0)
                    if isinstance(raw_mark, dict):
                        mark = float(raw_mark.get("markPrice", 0.0) or 0.0)
                    else:
                        mark = float(raw_mark or 0.0)
                except Exception as exc:
                    mark = 0.0
            if mark:
                metrics.set_core_symbol_metric("mark_price", symbol=base_sym, value=mark)
                try:
                    metrics.MARK_PRICE.labels(symbol=base_sym, venue="binance").set(mark)
                except Exception as exc:
                    _log_suppressed("engine guard", exc)
        except Exception as exc:
            _log_suppressed("engine guard", exc)

    try:
        stale = _last_position_symbols - current_symbols
        for sym in stale:
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
        _last_position_symbols.clear()
        _last_position_symbols.update(current_symbols)
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    metrics.set_core_metric("mark_time_epoch", now_ts)
    metrics.set_core_metric("metrics_heartbeat", now_ts)
    try:
        metrics.engine_component_uptime_seconds.labels(component=ROLE).set(
            now_ts - _ENGINE_START_TS
        )
    except ValueError:
        pass
    _snapshot_counter += 1
    metrics.set_core_metric("snapshot_id", _snapshot_counter)


async def _refresh_venue_data() -> None:
    """Background task to refresh price map, basis cache, and account totals from venue."""
    global _price_map, _basis_cache, _snapshot_counter

    if VENUE != "BINANCE":
        return

    try:
        _refresh_logger.info(
            "Starting venue refresh loop (pid=%s, venue=%s, futures=%s)",
            os.getpid(),
            VENUE,
            settings.is_futures,
        )
    except Exception as exc:
        _log_suppressed("engine guard", exc)

    while True:
        try:
            if settings.is_futures:
                await _refresh_binance_futures_snapshot()
            else:
                await _refresh_binance_spot_snapshot()
        except Exception as exc:
            try:
                _refresh_logger.exception("refresh loop error")
            except Exception as exc:
                _log_suppressed("engine guard", exc)
        await asyncio.sleep(5)


@app.on_event("shutdown")
async def _shutdown_background_tasks() -> None:
    try:
        await runtime_tasks.shutdown()
    except Exception as exc:
        logging.getLogger(__name__).exception("Background task shutdown failed")


@app.on_event("startup")
def _init_prom_multiproc_dir() -> None:
    """Ensure PROMETHEUS_MULTIPROC_DIR exists and clear stale DBs on each worker boot."""
    try:
        import os
        import pathlib

        default_prom_dir = os.path.join(tempfile.gettempdir(), "prom_multiproc")
        mp = os.getenv("PROMETHEUS_MULTIPROC_DIR", default_prom_dir)
        path = pathlib.Path(mp)
        path.mkdir(parents=True, exist_ok=True)

        for f in path.glob("*.db"):
            try:
                f.unlink()
            except FileNotFoundError:
                continue
            except Exception as exc:
                _log_suppressed("engine guard", exc)
        try:
            _startup_logger.info("Prometheus multiprocess directory: %s", path)
        except Exception as exc:
            _log_suppressed("engine guard", exc)
    except Exception as exc:
        _log_suppressed("engine guard", exc)


@app.get("/events/stats")
def get_event_stats() -> dict[str, Any]:
    """Get event bus statistics."""
    return {"event_bus": BUS.get_stats() if hasattr(BUS, "get_stats") else {}}


@app.get("/alerts/stats")
def get_alert_stats() -> dict[str, Any]:
    """Get alerting system statistics."""
    daemon = cast("AlertDaemon | None", getattr(alert_daemon, "_alert_daemon", None))
    stats = daemon.get_stats() if daemon is not None else {}
    return {"alerting": stats}


@app.get("/limits")
def get_limits() -> dict[str, Any]:
    cfg = RAILS.cfg
    return {
        "trading_enabled": cfg.trading_enabled,
        "min_notional_usdt": cfg.min_notional_usdt,
        "max_notional_usdt": cfg.max_notional_usdt,
        "max_orders_per_min": cfg.max_orders_per_min,
        "exposure_cap_symbol_usd": cfg.exposure_cap_symbol_usd,
        "exposure_cap_total_usd": cfg.exposure_cap_total_usd,
    }


@app.get("/risk/config")
def get_risk_config() -> dict[str, Any]:
    """Return current risk rails configuration (live values)."""
    cfg = RAILS.cfg
    return {
        "trading_enabled": cfg.trading_enabled,
        "min_notional_usdt": cfg.min_notional_usdt,
        "max_notional_usdt": cfg.max_notional_usdt,
        "max_orders_per_min": cfg.max_orders_per_min,
        "exposure_cap_symbol_usd": cfg.exposure_cap_symbol_usd,
        "exposure_cap_total_usd": cfg.exposure_cap_total_usd,
        "venue_error_breaker_pct": cfg.venue_error_breaker_pct,
        "venue_error_window_sec": cfg.venue_error_window_sec,
    }


@app.post("/risk/reload")
def reload_risk_config() -> dict[str, Any]:
    """Hot-reload risk configuration from environment variables."""
    from engine.config import load_risk_config

    RAILS.cfg = load_risk_config()
    metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
    try:
        metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    cfg = RAILS.cfg
    return {
        "status": "ok",
        "trading_enabled": cfg.trading_enabled,
        "min_notional_usdt": cfg.min_notional_usdt,
        "max_notional_usdt": cfg.max_notional_usdt,
        "max_orders_per_min": cfg.max_orders_per_min,
    }


class TradingToggle(BaseModel):
    enabled: bool


@app.post("/ops/trading")
async def toggle_trading(body: TradingToggle, request: Request) -> dict[str, Any]:
    """Toggle trading enablement via authenticated Ops control."""
    require_ops_token(request)
    enabled = bool(body.enabled)
    RAILS.cfg = replace(RAILS.cfg, trading_enabled=enabled)
    try:
        metrics.set_trading_enabled(enabled)
    except Exception as exc:
        _log_suppressed("engine guard", exc)
    try:
        await router.set_trading_enabled(enabled)
    except Exception as exc:
        logging.getLogger("engine.ops_auth").warning(
            "Failed to persist trading flag", exc_info=True
        )
    return {"status": "ok", "trading_enabled": enabled}


@app.get("/governance/status")
def get_governance_status() -> dict[str, Any]:
    """Get autonomous governance system status."""
    try:
        from ops import governance_daemon

        snapshot = governance_daemon.get_governance_status()
    except Exception as exc:
        return {"governance": {"status": "error", "error": str(exc)}}
    else:
        return {"governance": snapshot}


@app.post("/governance/reload")
def reload_governance_policies() -> dict[str, Any]:
    """Hot-reload governance policies."""
    try:
        from ops import governance_daemon

        success = governance_daemon.reload_governance_policies()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    else:
        return {"status": "success" if success else "failed"}


@app.get("/governance/actions")
def list_governance_actions(limit: int = 20) -> dict[str, Any]:
    """Return the most recent governance actions (audit log)."""
    try:
        from ops import governance_daemon

        actions = governance_daemon.get_recent_governance_actions(limit)
    except Exception as exc:
        return {"actions": [], "error": str(exc)}
    else:
        return {"actions": actions, "limit": limit}


@app.post("/governance/simulate/{event_type}")
async def simulate_governance_event(event_type: str) -> dict[str, Any]:
    """Simulate governance triggers for testing."""
    # Simulate different types of events that would trigger governance
    test_events: dict[str, dict[str, Any]] = {
        "poor_performance": {
            "pnl_unrealized": -150.0,
            "sharpe": 0.05,
            "equity_usd": 9850.0,
        },
        "great_performance": {
            "pnl_unrealized": 120.0,
            "sharpe": 2.5,
            "equity_usd": 10120.0,
        },
        "risk_breach": {
            "symbol": "BTCUSDT.BINANCE",
            "side": "BUY",
            "reason": "EXPOSURE_LIMIT",
        },
        "market_stress": {"spread_pct": 0.03, "volatility_spike": True},
    }

    if event_type not in test_events:
        return {"status": "error", "message": f"Unknown event type: {event_type}"}

    payload = test_events[event_type]
    try:
        if event_type in {"poor_performance", "great_performance"}:
            await BUS.publish("metrics.update", payload)
        elif event_type == "risk_breach":
            await BUS.publish("risk.rejected", payload)
        elif event_type == "market_stress":
            await BUS.publish("price.anomaly", payload)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    else:
        return {"status": f"simulated {event_type}", "data": payload}
@app.post("/ops/flatten")
async def flatten_positions(request: Request) -> dict[str, Any]:
    """Emergency flatten all positions."""
    require_ops_token(request)
    try:
        body = await request.json()
        reason = body.get("reason", "manual_flatten")
    except Exception as exc:
        reason = "manual_flatten"

    flattened = []
    failed = []
    
    # 1. Flatten via OrderRouter (Best Effort)
    try:
        if order_router and portfolio:
            positions = portfolio.state.positions
            for symbol, pos in positions.items():
                qty = pos.qty_base
                if qty == 0:
                    continue
                
                side = "SELL" if qty > 0 else "BUY"
                abs_qty = abs(qty)
                
                try:
                    # Submit market order to close
                    await order_router.submit_order(
                        symbol=symbol,
                        side=side,
                        quantity=abs_qty,
                        order_type="MARKET",
                        reduce_only=True,
                        tag="flatten"
                    )
                    flattened.append({"symbol": symbol, "qty": abs_qty, "side": side})
                except Exception as e:
                    failed.append({"symbol": symbol, "error": str(e)})
    except Exception as e:
        _app_logger.error("Flatten failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}

    return {
        "status": "success",
        "flattened": flattened,
        "failed": failed,
        "requested": len(flattened) + len(failed),
        "succeeded": len(flattened)
    }
