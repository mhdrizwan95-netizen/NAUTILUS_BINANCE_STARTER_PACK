from __future__ import annotations

import asyncio
import inspect
import time
import json
import logging
import math
import random
import threading
from contextlib import suppress
from functools import partial
from threading import Lock
from pathlib import Path
from typing import Literal, Optional, Any, Callable, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
import json
import httpx as _httpx

import os
from engine.config import get_settings, load_risk_config, QUOTE_CCY
from engine.core.binance import BinanceREST, BinanceMarginREST
from engine.core.kraken import KrakenREST
from engine.core.binance_ws import BinanceWS
from engine.ops.bracket_governor import BracketGovernor
from engine.core.order_router import OrderRouterExt, set_exchange_client, _MDAdapter
from engine.ops.stop_validator import StopValidator
from engine.core.portfolio import Portfolio, Position
from engine.core.event_bus import BUS, initialize_event_bus, publish_order_event, publish_risk_event
from engine.core.signal_queue import SIGNAL_QUEUE, QueuedEvent
from engine.core import alert_daemon
from engine.risk import RiskRails
from engine import metrics
from engine.idempotency import CACHE, append_jsonl
from engine.state import SnapshotStore
import engine.state as state_mod
from engine.reconcile import reconcile_since_snapshot
from engine.telemetry.publisher import (
    publish_metrics as deck_publish_metrics,
    publish_fill as deck_publish_fill,
    record_equity,
    latency_quantiles,
)
from engine import strategy
from engine.universe import configured_universe, last_prices
from engine.telemetry.publisher import (
    publish_metrics as deck_publish_metrics,
    publish_fill as deck_publish_fill,
    latency_percentiles as deck_latency_percentiles,
    record_realized_total as deck_record_realized_total,
    consume_latency as deck_consume_latency,
)
from engine.feeds.market_data_dispatcher import MarketDataDispatcher, MarketDataLogger

app = FastAPI(title="HMM Engine", version="0.1.0")

def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

settings = get_settings()
ROLE = os.getenv("ROLE", "trader").lower()
IS_EXPORTER = ROLE == "exporter"
VENUE = os.getenv("VENUE", "BINANCE").upper()
risk_cfg = load_risk_config()
RAILS = RiskRails(risk_cfg)
DECK_PUSH_DISABLED = os.getenv("DECK_DISABLE_PUSH", "").lower() in {"1", "true", "yes"}
DECK_METRICS_INTERVAL_SEC = max(1.0, float(os.getenv("DECK_METRICS_INTERVAL_SEC", "2.0")))
_deck_metrics_task: Optional[asyncio.Task] = None
_deck_realized_lock = Lock()
_deck_last_realized = 0.0
_market_data_dispatcher: Optional[MarketDataDispatcher] = None
_market_data_logger: Optional[MarketDataLogger] = None
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
AUTO_TOPUP_ENABLED = os.getenv("AUTO_TOPUP_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
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


class _DummyBinanceREST:
    """Lightweight offline stub used when API credentials are absent."""

    def __init__(self):
        self._price = float(os.getenv("DUMMY_BINANCE_PRICE", "20000"))

    async def account_snapshot(self):
        return {
            "balances": [{"asset": "USDT", "free": 1000.0, "locked": 0.0}],
            "positions": [],
        }

    async def submit_market_quote(self, symbol: str, side: str, quote: float, market: str | None = None):
        qty = float(quote) / self._price if self._price else float(quote)
        return {
            "symbol": symbol,
            "executedQty": qty,
            "filled_qty_base": qty,
            "avg_fill_price": self._price,
            "status": "FILLED",
        }

    async def submit_market_order(self, symbol: str, side: str, quantity: float, market: str | None = None, reduce_only: bool = False):
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

    def get_last_price(self, symbol: str, market: str | None = None):
        price = self.ticker_price(symbol)
        if isinstance(price, dict):
            return float(price.get("price", self._price))
        try:
            return float(price)
        except Exception:
            return self._price

    def ticker_price(self, symbol: str, market: str | None = None):
        return {"price": self._price}

    def my_trades_since(self, symbol: str, start_ms: int):
        return []

    async def order_status(self, symbol: str, *, order_id: int | str | None = None, client_order_id: str | None = None):
        return {
            "symbol": symbol,
            "orderId": order_id or 0,
            "status": "FILLED",
            "executedQty": float("nan"),
            "avgPrice": self._price,
        }

    async def safe_price(self, symbol: str):
        return self._price

    async def exchange_filter(self, symbol: str):
        class _Filter:
            step_size = 0.0001
            min_qty = 0.0001
            min_notional = 5.0
            max_notional = 1_000_000.0
            tick_size = 0.0001

        return _Filter()

    async def refresh_portfolio(self):
        return None

    async def bulk_premium_index(self):
        return {}

    async def account(self):
        return {}

    async def position_risk(self):
        return []

    async def hedge_mode(self):
        return False


if VENUE == "BINANCE":
    if not settings.api_key or not settings.api_secret:
        rest_client = _DummyBinanceREST()
    else:
        rest_client = BinanceREST()
elif VENUE == "KRAKEN":
    rest_client = KrakenREST()
else:
    rest_client = BinanceREST()

margin_rest_client: Optional[BinanceMarginREST]
if _truthy_env("MARGIN_ENABLED") or _truthy_env("BINANCE_MARGIN_ENABLED"):
    if settings.api_key and settings.api_secret:
        try:
            margin_rest_client = BinanceMarginREST()
            set_exchange_client("BINANCE_MARGIN", margin_rest_client)
        except Exception as margin_exc:  # noqa: BLE001
            logging.getLogger("engine.startup").warning(
                "[STARTUP] Failed to initialize margin REST client: %s", margin_exc
            )
            margin_rest_client = None
    else:
        margin_rest_client = None
else:
    margin_rest_client = None

MARGIN_REST = margin_rest_client

if VENUE == "KRAKEN":
    KRAKEN_REST: KrakenREST | None = cast(Optional[KrakenREST], rest_client)
else:
    KRAKEN_REST = None


def _kraken_configured_products() -> list[str]:
    raw = os.getenv("KRAKEN_TRADED_SYMBOLS") or "PI_XBTUSD.KRAKEN,PI_ETHUSD.KRAKEN"
    values: list[str] = []
    for token in raw.split(","):
        item = token.strip()
        if not item:
            continue
        values.append(item.split(".")[0].strip().upper())
    if not values:
        values.append("PI_XBTUSD")
    return sorted(set(values))


def _kraken_symbol_base(symbol: str) -> str:
    return symbol.split(".")[0].upper()


_KRAKEN_PRODUCTS = _kraken_configured_products() if VENUE == "KRAKEN" else []
_KRAKEN_MARK_WARN_SEC = 5.0
_KRAKEN_MARK_PAGE_SEC = 15.0
_KRAKEN_MARK_FORCE_SEC = 60.0
_kraken_mark_ts: dict[str, float] = {}
_kraken_mark_alert_state: dict[str, int] = {}


async def _kraken_safe_price(symbol: str) -> float | None:
    if KRAKEN_REST is None:
        return None
    result = await KRAKEN_REST.safe_price(symbol)
    if isinstance(result, (int, float)) and math.isfinite(float(result)):
        return float(result)
    return None


def _kraken_record_mark(symbol: str, raw_price: float, ts: float) -> None:
    if VENUE != "KRAKEN":
        return
    base = _kraken_symbol_base(symbol)
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return
    if not math.isfinite(price) or price <= 0.0:
        return
    _kraken_mark_ts[base] = ts
    _kraken_mark_alert_state[base] = 0
    try:
        metrics.mark_price_freshness_sec.labels(symbol=base, venue="kraken").set(0.0)
        metrics.mark_price_by_symbol.labels(symbol=base).set(price)
        metrics.MARK_PRICE.labels(symbol=base, venue="kraken").set(price)
        _price_map[base] = price
    except Exception:
        pass
    if KRAKEN_REST is not None:
        try:
            KRAKEN_REST.cache_price(base, price)
        except Exception:
            pass


def _kraken_on_mark(qual: str, sym: str, price: float, ts: float) -> None:
    _kraken_record_mark(sym, price, ts)


# ---- Binance WebSocket mark handler -----------------------------------------
_binance_mark_ts: dict[str, float] = {}
_BINANCE_WS_SYMBOLS: list[str] = []

def _binance_on_mark(qual: str, sym: str, price: float, ts: float) -> None:
    base = sym.split(".")[0].upper() if "." in sym else sym.upper()
    try:
        price_f = float(price)
        if price_f <= 0:
            return
    except Exception:
        return
    _binance_mark_ts[base] = ts or time.time()
    try:
        metrics.MARK_PRICE.labels(symbol=base, venue="binance").set(price_f)
        metrics.mark_price_by_symbol.labels(symbol=base).set(price_f)
        metrics.mark_price_freshness_sec.labels(symbol=base, venue="binance").set(0.0)
        _price_map[base] = price_f
    except Exception:
        pass
    # Emit strategy tick + increment strategy_ticks_total via helper
    try:
        _maybe_emit_strategy_tick(
            qual,
            price_f,
            ts=ts or time.time(),
            source="binance_ws",
            stream="ws",
        )
    except Exception:
        pass


async def _kraken_refresh_mark_prices(now: float) -> None:
    if VENUE != "KRAKEN":
        return
    products = _KRAKEN_PRODUCTS or ["PI_XBTUSD"]
    for base in products:
        last_ts = _kraken_mark_ts.get(base)
        freshness = float("inf") if last_ts is None else max(0.0, now - last_ts)
        try:
            metrics.mark_price_freshness_sec.labels(symbol=base, venue="kraken").set(freshness)
        except Exception:
            pass

        state = _kraken_mark_alert_state.get(base, 0)
        if freshness >= _KRAKEN_MARK_PAGE_SEC and state < 2:
            _kraken_risk_logger.error("Kraken mark stale %.1fs (paging) for %s", freshness, base)
            state = 2
        elif freshness >= _KRAKEN_MARK_WARN_SEC and state < 1:
            _kraken_risk_logger.warning("Kraken mark stale %.1fs for %s", freshness, base)
            state = 1
        force_rest = freshness >= _KRAKEN_MARK_FORCE_SEC
        if force_rest and state < 3:
            _kraken_risk_logger.warning("Kraken mark stale %.1fs, forcing REST refresh for %s", freshness, base)
            state = 3
        _kraken_mark_alert_state[base] = state

        if freshness < _KRAKEN_MARK_WARN_SEC and last_ts is not None:
            continue

        price: float | None = None
        try:
            if force_rest:
                ticker = getattr(rest_client, "ticker_price", None)
                if callable(ticker):
                    candidate = ticker(base)
                    if inspect.isawaitable(candidate):
                        candidate = await candidate
                    if isinstance(candidate, (int, float)) and math.isfinite(float(candidate)):
                        price = float(candidate)
            else:
                price = await _kraken_safe_price(base)
        except Exception as exc:
            if force_rest:
                _kraken_risk_logger.error("Kraken REST price fetch failed for %s: %s", base, exc)
            else:
                _kraken_risk_logger.debug("Kraken safe_price failed for %s: %s", base, exc)
            price = None

        if isinstance(price, (int, float)) and price > 0.0:
            _kraken_record_mark(base, float(price), now)
            continue

        try:
            metrics.MARK_PRICE.labels(symbol=base, venue="kraken").set(0.0)
            metrics.mark_price_by_symbol.labels(symbol=base).set(0.0)
        except Exception:
            pass


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
        except Exception as exc:
            _AUTO_TOPUP_LOG.warning("auto_topup: failure: %s", exc)
        await asyncio.sleep(period)


async def wallet_balance_worker() -> None:
    """Poll Binance for wallet balances and expose them via Deck metrics."""
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

    while True:
        try:
            timestamp = time.time()
            futures_total = futures_available = 0.0
            try:
                futures_snapshot = await rest.account_snapshot(market="futures")
                futures_total = _as_float(futures_snapshot.get("totalWalletBalance"))
                futures_available = _as_float(futures_snapshot.get("availableBalance"))
            except Exception as fut_exc:
                _WALLET_LOG.debug("wallet monitor: futures snapshot failed (%s)", fut_exc)

            spot_free = spot_locked = 0.0
            spot_snapshot: dict[str, Any] = {}
            margin_level = 0.0
            margin_liability_usd = 0.0
            try:
                margin_snapshot = await rest.margin_account()
                margin_level = _as_float(margin_snapshot.get("marginLevel"))
                liability_btc = _as_float(margin_snapshot.get("totalLiabilityOfBtc"))
                if liability_btc > 0:
                    try:
                        btc_px = await rest.ticker_price("BTCUSDT", market="spot")
                    except Exception:
                        btc_px = spot_snapshot.get("lastPrice") if spot_snapshot else 0.0
                    margin_liability_usd = liability_btc * _as_float(btc_px)
            except Exception as margin_exc:
                _WALLET_LOG.debug("wallet monitor: margin snapshot failed (%s)", margin_exc)

            try:
                spot_snapshot = await rest.account_snapshot(market="spot") or {}
                for balance in spot_snapshot.get("balances", []) or []:
                    if str(balance.get("asset", "")).upper() == "USDT":
                        spot_free = _as_float(balance.get("free"))
                        spot_locked = _as_float(balance.get("locked"))
                        break
            except Exception as spot_exc:
                _WALLET_LOG.debug("wallet monitor: spot snapshot failed (%s)", spot_exc)

            funding_free = 0.0
            try:
                funding_free = _as_float(await rest.funding_balance("USDT"))
            except Exception as fund_exc:
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
            try:
                state = portfolio.state
                state.equity = total_equity
                state.cash = funding_free + spot_total + futures_available
                state.margin_level = margin_level
                state.margin_liability_usd = margin_liability_usd
                setattr(state, "wallet_breakdown", snapshot)
            except Exception:
                pass
            try:
                metrics.margin_level.set(float(margin_level))
                metrics.margin_liability_usd.set(float(margin_liability_usd))
            except Exception:
                pass
        except asyncio.CancelledError:
            _WALLET_LOG.warning("wallet monitor: cancelled")
            raise
        except Exception as exc:
            _WALLET_LOG.warning("wallet monitor: error: %s", exc)
        await asyncio.sleep(period)


portfolio = Portfolio()
try:
    _deck_last_realized = float(getattr(portfolio.state, "realized", 0.0) or 0.0)
except Exception:
    _deck_last_realized = 0.0
router = OrderRouterExt(rest_client, portfolio, venue=VENUE)
order_router = router
try:
    # Expose BUS on router for event publishing (e.g., trade.fill)
    router.bus = BUS  # type: ignore[attr-defined]
except Exception:
    pass
startup_lock = asyncio.Lock()
_refresh_logger = logging.getLogger("engine.refresh")
_startup_logger = logging.getLogger("engine.startup")
_persist_logger = logging.getLogger("engine.persistence")
_kraken_risk_logger = logging.getLogger("engine.kraken.telemetry")
_deck_logger = logging.getLogger("engine.deck")


def _deck_symbol(base: str, venue: str) -> str:
    base = base.upper()
    if "." in base:
        return base
    venue_norm = venue.upper() if venue else VENUE
    return f"{base}.{venue_norm}"


def _deck_fill_handler(event: dict[str, Any]) -> None:
    if DECK_PUSH_DISABLED:
        return
    global _deck_last_realized
    try:
        base = str(event.get("symbol") or "").upper()
        venue = str(event.get("venue") or VENUE).upper()
        if not base:
            return
        symbol = _deck_symbol(base, venue)
        latency_ms = deck_consume_latency(symbol) or deck_consume_latency(base) or 0.0
        meta = event.get("strategy_meta") or {}
        try:
            pnl_meta = float(meta.get("pnl_usd", 0.0))
        except (TypeError, ValueError):
            pnl_meta = 0.0
        pnl_usd = pnl_meta
        try:
            global _deck_last_realized
            with _deck_realized_lock:
                current_realized = float(getattr(portfolio.state, "realized", 0.0) or 0.0)
                delta = current_realized - _deck_last_realized
                _deck_last_realized = current_realized
            if abs(delta) > 1e-9:
                pnl_usd = delta
        except Exception:
            pass
        strategy_name = (
            event.get("strategy_tag")
            or meta.get("strategy")
            or event.get("intent")
            or "unclassified"
        )
        fill_payload = {
            "ts": float(event.get("ts") or time.time()),
            "strategy": str(strategy_name),
            "symbol": symbol,
            "side": str(event.get("side") or "").lower(),
            "pnl_usd": pnl_usd,
            "latency_ms": float(latency_ms or 0.0),
            "info": {
                "order_id": event.get("order_id"),
                "qty": event.get("filled_qty"),
                "price": event.get("avg_price"),
                "intent": event.get("intent"),
            },
        }
        fill_payload["info"] = {k: v for k, v in fill_payload["info"].items() if v is not None}
        deck_publish_fill(fill_payload)
    except Exception as exc:  # pragma: no cover - telemetry best effort
        _deck_logger.debug("Deck fill publish failed: %s", exc)


async def _deck_metrics_loop() -> None:
    if DECK_PUSH_DISABLED or IS_EXPORTER:
        return
    loop = asyncio.get_running_loop()
    while True:
        try:
            await asyncio.sleep(DECK_METRICS_INTERVAL_SEC)
            state = portfolio.state
            equity = float(getattr(state, "equity", 0.0) or 0.0)
            realized = float(getattr(state, "realized", 0.0) or 0.0)
            pnl_24h = deck_record_realized_total(realized)
            p50, p95 = deck_latency_percentiles()
            try:
                positions_open = sum(
                    1
                    for pos in (state.positions or {}).values()
                    if abs(getattr(pos, "quantity", 0.0) or 0.0) > 0.0
                )
            except Exception:
                positions_open = 0
            breaker_flags = {
                "equity": RAILS.equity_breaker_open(),
                "venue": RAILS.venue_breaker_open(),
            }
            drawdown_pct = RAILS.current_drawdown_pct()
            error_rate_pct = RAILS.current_error_rate_pct()
            publish_fn = partial(
                deck_publish_metrics,
                equity_usd=equity,
                pnl_24h=pnl_24h,
                drawdown_pct=drawdown_pct,
                positions=positions_open,
                tick_p50_ms=p50,
                tick_p95_ms=p95,
                error_rate_pct=error_rate_pct,
                breaker=breaker_flags,
                pnl_by_strategy=None,
            )
            await loop.run_in_executor(None, publish_fn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - telemetry best effort
            _deck_logger.debug("Deck metrics publish failed: %s", exc)

_DECK_BRIDGE_ENABLED = os.getenv("DECK_BRIDGE_DISABLED", "false").lower() not in {"1", "true", "yes"}


def _deck_thread_wrapper(func, args, kwargs):
    try:
        func(*args, **kwargs)
    except Exception:
        pass


def _queue_deck_call(func, *args, **kwargs) -> None:
    if not _DECK_BRIDGE_ENABLED:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(target=_deck_thread_wrapper, args=(func, args, kwargs), daemon=True).start()
        return
    loop.create_task(asyncio.to_thread(func, *args, **kwargs))


def _queue_deck_metrics(pnl_by_strategy: dict[str, float] | None = None) -> None:
    if not _DECK_BRIDGE_ENABLED:
        return
    try:
        state = portfolio.state
    except Exception:
        return

    equity = float(getattr(state, "equity", 0.0) or 0.0)
    wallet_snapshot = _wallet_state_copy()
    wallet_equity = _safe_float(wallet_snapshot.get("total_equity_usdt")) if wallet_snapshot else None
    if wallet_equity is not None:
        equity = wallet_equity
    now = time.time()
    pnl_24h, drawdown_pct = record_equity(equity, now=now)
    positions_count = len(getattr(state, "positions", {}) or {})
    tick_p50, tick_p95 = latency_quantiles()

    try:
        error_rate_pct = RAILS.current_error_rate_pct()
    except Exception:
        error_rate_pct = 0.0

    try:
        breaker_equity = RAILS.equity_breaker_open()
    except Exception:
        breaker_equity = False
    try:
        breaker_venue = RAILS.venue_breaker_open()
    except Exception:
        breaker_venue = False

    metrics_kwargs = {
        "equity_usd": equity,
        "pnl_24h": pnl_24h,
        "drawdown_pct": drawdown_pct,
        "positions": positions_count,
        "tick_p50_ms": tick_p50,
        "tick_p95_ms": tick_p95,
        "error_rate_pct": error_rate_pct,
        "breaker": {"equity": breaker_equity, "venue": breaker_venue},
        "pnl_by_strategy": pnl_by_strategy,
    }

    if wallet_snapshot:
        wallet_fields = {
            "wallet_timestamp": wallet_snapshot.get("timestamp"),
            "funding_free_usdt": wallet_snapshot.get("funding_free_usdt"),
            "spot_free_usdt": wallet_snapshot.get("spot_free_usdt"),
            "spot_locked_usdt": wallet_snapshot.get("spot_locked_usdt"),
            "spot_total_usdt": wallet_snapshot.get("spot_total_usdt"),
            "futures_wallet_usdt": wallet_snapshot.get("futures_wallet_usdt"),
            "futures_available_usdt": wallet_snapshot.get("futures_available_usdt"),
            "total_equity_usdt": wallet_snapshot.get("total_equity_usdt"),
        }
        for key, value in wallet_fields.items():
            if value is None:
                continue
            metrics_kwargs[key] = value

    try:
        snapshot = dict(portfolio.snapshot())
        snapshot["equity_usd"] = equity
        snapshot["cash_usd"] = float(getattr(state, "cash", 0.0) or 0.0)
        RAILS.refresh_snapshot_metrics(snapshot, venue=VENUE)
    except Exception:
        pass

    _queue_deck_call(deck_publish_metrics, **metrics_kwargs)

store = None
try:
    from engine.storage import sqlite as _sqlite_store
    _sqlite_store.init()
    store = _sqlite_store
    _persist_logger.info("SQLite persistence initialized at %s", Path("data/runtime/trades.db").resolve())
except Exception:
    _persist_logger.exception("SQLite initialization failed")

# Attach metrics router
app.include_router(metrics.router)
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
try:
    metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
except Exception:
    pass
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
        "TRADING_ENABLED", "MIN_NOTIONAL_USDT", "MAX_NOTIONAL_USDT", "MAX_ORDERS_PER_MIN",
        "TRADE_SYMBOLS", "DUST_THRESHOLD_USD",
        "EXPOSURE_CAP_SYMBOL_USD", "EXPOSURE_CAP_TOTAL_USD",
        "VENUE_ERROR_BREAKER_PCT", "VENUE_ERROR_WINDOW_SEC",
    ]
    import os
    blob = "|".join(f"{k}={os.getenv(k, '')}" for k in keys)
    import hashlib
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _maybe_emit_strategy_tick(
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
    try:
        qualified = symbol if "." in symbol else f"{symbol}.BINANCE"
        base = qualified.split(".")[0].upper()
        venue = qualified.split(".")[1].upper() if "." in qualified else "BINANCE"
        # Always count ticks for observability, even if strategy disabled
        try:
            metrics.strategy_ticks_total.labels(symbol=base, venue=venue.lower()).inc()
        except Exception:
            pass
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
            try:
                BUS.fire("market.tick", payload)
                delivered_via_bus = bool(getattr(BUS, "_running", False))
            except Exception:
                delivered_via_bus = False
        if skip_bus:
            return
        if delivered_via_bus:
            return
        cfg = getattr(strategy, "S_CFG", None)
        if cfg is not None and getattr(cfg, "enabled", False):
            strategy.on_tick(qualified, float(price), event_ts, volume)
    except Exception:
        try:
            _refresh_logger.debug("Strategy tick emit failed for %s", symbol, exc_info=True)
        except Exception:
            pass

@app.get("/readyz")
def readyz():
    """Lightweight readiness probe with only in-process checks."""
    try:
        snap_ok = bool(getattr(router, "snapshot_loaded", False))
    except Exception:
        snap_ok = False
    return {"ok": True, "snapshot_loaded": snap_ok, "mode": settings.mode}


@app.get("/version")
def version():
    """Return build provenance and model info."""
    import os
    return {
        "git_sha": os.getenv("GIT_SHA", "dev"),
        "model_tag": os.getenv("MODEL_TAG", "hmm_v1"),
        "config_hash": _config_hash(),
        "build_at": os.getenv("BUILD_AT", ""),
    }


@app.post("/events/external", status_code=202)
async def enqueue_external_event(evt: ExternalEventRequest):
    """Expose a lightweight ingress for external (off-tick) strategy signals."""

    try:
        await _queue_external_event(evt)
    except Exception as exc:  # noqa: BLE001
        metrics.external_feed_errors_total.labels(evt.source).inc()
        _external_event_logger.warning(
            "Failed to enqueue external event from %s: %s", evt.source, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="failed to enqueue external event") from exc
    return {"status": "queued", "topic": "events.external_feed"}


_store = SnapshotStore(state_mod.SNAP_PATH)
_boot_status = {"snapshot_loaded": False, "reconciled": False}
_last_reconcile_ts = 0.0  # Track reconcile freshness
_last_specs_refresh = 0.0  # Track venue specs freshness
_basis_cache = {}  # {symbol: {entry_price, position_amt, last_sync_epoch}}
# Track last symbols we emitted per-symbol metrics for cleanup when positions close
_last_position_symbols: set[str] = set()
_price_map = {}  # symbol -> markPrice
_snapshot_counter = 0

_kraken_risk_loop_task: asyncio.Task | None = None
_kraken_risk_stop_event = asyncio.Event()


class ExternalEventRequest(BaseModel):
    """Schema for enqueuing external feed events via the API."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Canonical feed identifier")
    payload: dict[str, Any] = Field(default_factory=dict, description="Arbitrary event payload")
    asset_hints: list[str] = Field(default_factory=list, description="Optional trading symbols impacted")
    priority: float = Field(0.5, ge=0.0, le=1.0, description="Queue priority [0.0, 1.0]")
    expires_at: float | None = Field(
        default=None, description="Optional epoch timestamp at which the event becomes stale"
    )
    ttl_sec: float | None = Field(
        default=None, ge=0.0, description="Alternative to expires_at: TTL in seconds"
    )

    @field_validator("source")
    @classmethod
    def _normalize_source(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source must be non-empty")
        return cleaned

    @field_validator("payload", mode="before")
    @classmethod
    def _default_payload(cls, value):
        return value or {}

    @field_validator("asset_hints", mode="before")
    @classmethod
    def _coerce_hints(cls, value):
        if value is None:
            return []
        if isinstance(value, (str, bytes)):
            return [value]
        return list(value)

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
    quote: Optional[float] = Field(None, gt=0, description="Quote currency amount (USDT).")
    quantity: Optional[float] = Field(None, gt=0, description="Base asset quantity.")
    market: Optional[str] = Field(None, description="Preferred market within venue (spot/futures/margin).")
    venue: Optional[str] = Field(None, description="Trading venue. Defaults to VENUE env var.")

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_exclusive(self):
        if (self.quantity is None) == (self.quote is None):
            raise ValueError("Set exactly one of quote or quantity.")
        return self


class LimitOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., description="e.g., BTCUSDT.BINANCE")
    side: Literal["BUY", "SELL"]
    price: float = Field(..., gt=0, description="Limit price")
    timeInForce: Literal["IOC", "FOK", "GTC"] = Field("IOC")
    quote: Optional[float] = Field(None, gt=0, description="Quote currency amount (USDT).")
    quantity: Optional[float] = Field(None, gt=0, description="Base asset quantity.")
    market: Optional[str] = Field(None, description="Preferred market within venue (spot/futures/margin).")

    @model_validator(mode="after")
    def validate_exclusive(self):
        if (self.quantity is None) == (self.quote is None):
            raise ValueError("Set exactly one of quote or quantity.")
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
    except Exception:
        pass


@app.on_event("startup")
async def on_startup() -> None:
    async with startup_lock:
        _startup_logger.info("Startup sequence started (role=%s, venue=%s)", ROLE, VENUE)
        try:
            h = _config_hash()
            flags = {k: os.getenv(k) for k in [
                "EVENT_BREAKOUT_ENABLED","EVENT_BREAKOUT_DRY_RUN","EVENT_BREAKOUT_METRICS",
                "DEX_FEED_ENABLED","SCALP_MAKER_SHADOW","ALLOW_STOP_AMEND","AUTO_CUTBACK_ENABLED",
                "RISK_PARITY_ENABLED","DEPEG_GUARD_ENABLED","FUNDING_GUARD_ENABLED"
            ] if os.getenv(k) is not None}
            _startup_logger.info("Config hash=%s flags=%s", h, flags)
        except Exception:
            pass
        # Start event bus early so other tasks can publish
        try:
            await initialize_event_bus()
            _startup_logger.info("Event bus initialized")
        except Exception:
            _startup_logger.warning("Event bus init failed", exc_info=True)
        await router.initialize_balances()
        # Optional: seed starting cash for demo/test if no balances detected
        try:
            import os
            state = portfolio.state
            if (state.cash is None or state.cash <= 0):
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
        metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)
        _startup_logger.info("Startup sequence completed")


async def _refresh_specs_periodically():
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
            if hasattr(metrics, 'REGISTRY') and 'last_specs_refresh_epoch' in metrics.REGISTRY:
                metrics.REGISTRY['last_specs_refresh_epoch'].set(_last_specs_refresh)
            logging.getLogger().info(f"Venue specs refreshed at {datetime.datetime.utcfromtimestamp(_last_specs_refresh)}")
        except Exception as e:
            logging.getLogger().error(f"Spec refresh failed: {e}")
        await asyncio.sleep(86400)  # 24h


@app.on_event("startup")
async def _start_specs_refresh():
    """Start the background venue specs refresh task."""
    asyncio.create_task(_refresh_specs_periodically())
    _startup_logger.info("Scheduled venue specs refresh task")


@app.on_event("startup")
async def _start_auto_topup_loop():
    if IS_EXPORTER or VENUE != "BINANCE":
        return
    if not AUTO_TOPUP_ENABLED:
        _AUTO_TOPUP_LOG.info("auto_topup: disabled; worker not started")
        return
    asyncio.create_task(auto_topup_worker(), name="auto-topup")


@app.on_event("startup")
async def _start_wallet_monitor():
    if IS_EXPORTER or VENUE != "BINANCE":
        return
    if not (settings.api_key and settings.api_secret):
        _WALLET_LOG.info("wallet monitor: credentials missing; not starting")
        return
    asyncio.create_task(wallet_balance_worker(), name="wallet-balance")


@app.on_event("startup")
async def _init_multi_venue_clients():
    """Initialize and register multi-venue exchange clients."""
    if IS_EXPORTER:
        return
    try:
        from engine.connectors.ibkr_client import IbkrClient
        import os
        # Only initialize IBKR if connection details are provided
        if os.getenv("IBKR_HOST"):
            ibkr_client = IbkrClient()
            set_exchange_client("IBKR", ibkr_client)
            _startup_logger.info("IBKR client initialized and registered")
    except ImportError:
        _startup_logger.warning("IBKR client not available - ib-insync not installed", exc_info=True)
    except Exception as e:
        _startup_logger.exception("IBKR client initialization failed: %s", e)


@app.on_event("startup")
async def _start_reconciliation():
    """Start the order state reconciliation daemon."""
    try:
        from engine.core.reconcile_daemon import reconcile_loop
        asyncio.create_task(reconcile_loop())
        _startup_logger.info("Reconciliation daemon started")
    except ImportError:
        _startup_logger.warning("Reconciliation module not available", exc_info=True)
    except Exception:
        _startup_logger.exception("Reconciliation daemon startup failed")


# Optional: start risk guardian and DEX feed when enabled via env
_GUARDIAN = None
_DEX_SNIPER = None
_DEX_WATCHER = None


@app.on_event("startup")
async def _start_guardian_and_feeds():
    if IS_EXPORTER:
        return
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
                BUS.subscribe("risk.cross_health_soft", risk_handlers.on_cross_health_soft(router, cfg))
                BUS.subscribe("risk.cross_health_critical", risk_handlers.on_cross_health_critical(router, cfg))
            except Exception:
                _startup_logger.warning("Risk handlers did not wire", exc_info=True)
    except Exception:
        _startup_logger.warning("Risk guardian failed to start", exc_info=True)

    # DEX feed loop
    try:
        import os
        if os.getenv("DEX_FEED_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.feeds.dexscreener import dexscreener_loop
            asyncio.create_task(dexscreener_loop(), name="dexscreener-feed")
            _startup_logger.info("DEX Screener feed started")
    except Exception:
        _startup_logger.warning("DEX Screener feed failed to start", exc_info=True)

    # DEX sniper wiring
    try:
        from engine.dex import DexExecutor, DexState, load_dex_config
        from engine.dex.wallet import DexWallet
        from engine.dex.router import DexRouter
        from engine.dex.oracle import DexPriceOracle
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
            router = DexRouter(web3=wallet.w3, router_address=dex_cfg.router_address)
            state = DexState(dex_cfg.state_path)
            executor = DexExecutor(
                wallet=wallet,
                router=router,
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
    except Exception:
        _startup_logger.warning("DEX sniper wiring failed", exc_info=True)

    # Binance announcements poller (publish-only)
    try:
        import os
        if os.getenv("ANN_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.feeds.binance_announcements import run as ann_run
            asyncio.create_task(ann_run(), name="binance-announcements")
            _startup_logger.info("Binance announcements poller started")
            # Optional: breakout handler wiring
            if os.getenv("EVENT_BREAKOUT_ENABLED", "").lower() in {"1", "true", "yes"}:
                from engine.handlers.breakout_handlers import on_binance_listing
                BUS.subscribe("events.external_feed", on_binance_listing(router))
                _startup_logger.info("Announcement breakout handler wired")
                # Trailing watcher (only when not dry-run and enabled)
                if os.getenv("EVENT_BREAKOUT_DRY_RUN", "").lower() not in {"1", "true", "yes"} and os.getenv("EVENT_BREAKOUT_TRAIL_LOOP_ENABLED", "").lower() in {"1", "true", "yes"}:
                    try:
                        from engine.strategies.event_breakout_trail import EventBreakoutTrailer
                        trailer = EventBreakoutTrailer(router)
                        asyncio.create_task(trailer.run())
                        _startup_logger.info("Event breakout trailing watcher started")
                    except Exception:
                        _startup_logger.warning("Failed to start event breakout trailer", exc_info=True)
    except Exception:
        _startup_logger.warning("Announcements poller failed to start", exc_info=True)

    # Momentum breakout module
    try:
        from engine.strategies.momentum_breakout import MomentumBreakout, load_momentum_config
        from engine import strategy as _strategy_mod

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
    except Exception:
        _startup_logger.warning("Momentum breakout wiring failed", exc_info=True)

    # Wire Event Breakout consumer (subscribe to strategy.event_breakout)
    try:
        if os.getenv("EVENT_BREAKOUT_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.strategies.event_breakout import EventBreakout
            bo = EventBreakout(router)
            # SIGHUP reload if denylist enabled
            if os.getenv("EVENT_BREAKOUT_DENYLIST_ENABLED", "").lower() in {"1", "true", "yes"}:
                try:
                    bo.enable_sighup_reload(bo.cfg.denylist_path)
                except Exception:
                    _startup_logger.info("SIGHUP not supported for denylist reload")
            # Entropy-based auto-denylist wiring
            if os.getenv("ENTROPY_DENY_ENABLED", "").lower() in {"1", "true", "yes"}:
                try:
                    BUS.subscribe("event_bo.skip", bo.on_skip_entropy)
                    _startup_logger.info("Entropy deny wiring enabled")
                except Exception:
                    pass
            BUS.subscribe("strategy.event_breakout", bo.on_event)
            _startup_logger.info("Event Breakout consumer wired")
    except Exception:
        _startup_logger.warning("Event Breakout consumer failed to wire", exc_info=True)

    # Meme sentiment strategy wiring
    try:
        from engine.strategies.meme_coin_sentiment import MemeCoinSentiment, load_meme_coin_config

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
        else:
            if _MEME_SENTIMENT is not None:
                try:
                    BUS.unsubscribe("events.external_feed", _MEME_SENTIMENT.on_external_event)
                except Exception:
                    pass
                _MEME_SENTIMENT = None
                _startup_logger.info("Meme sentiment strategy disabled via configuration")
    except Exception:
        _startup_logger.warning("Meme sentiment strategy wiring failed", exc_info=True)

    # Listing sniper wiring
    try:
        from engine.strategies.listing_sniper import ListingSniper, load_listing_sniper_config

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
        else:
            if _LISTING_SNIPER is not None:
                try:
                    BUS.unsubscribe("events.external_feed", _LISTING_SNIPER.on_external_event)
                except Exception:
                    pass
                try:
                    await _LISTING_SNIPER.shutdown()
                except Exception:
                    pass
                _LISTING_SNIPER = None
                _startup_logger.info("Listing sniper disabled via configuration")
    except Exception:
        _startup_logger.warning("Listing sniper wiring failed", exc_info=True)

    # Airdrop / promotion watcher wiring
    try:
        from engine.strategies.airdrop_promo import AirdropPromoWatcher, load_airdrop_promo_config

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
        else:
            if _AIRDROP_PROMO is not None:
                try:
                    BUS.unsubscribe("events.external_feed", _AIRDROP_PROMO.on_external_event)
                except Exception:
                    pass
                try:
                    await _AIRDROP_PROMO.shutdown()
                except Exception:
                    pass
                _AIRDROP_PROMO = None
                _startup_logger.info("Airdrop promo watcher disabled via configuration")
    except Exception:
        _startup_logger.warning("Airdrop promo watcher wiring failed", exc_info=True)

    # Start Telegram digest (if enabled)
    try:
        if os.getenv("TELEGRAM_ENABLED", "").lower() in {"1", "true", "yes"}:
            from ops.notify.telegram import Telegram
            from ops.notify.bridge import NotifyBridge
            from engine.telemetry.rollups import EventBORollup, EventBOBuckets
            from engine.ops.digest import DigestJob
            tg = Telegram(os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""), _startup_logger)
            # Notify bridge (relay BUS notify.telegram)
            bridge_enabled = os.getenv("TELEGRAM_BRIDGE_ENABLED", "true").lower() in {"1", "true", "yes"}
            try:
                NotifyBridge(tg, BUS, _startup_logger, enabled=bridge_enabled)
                _startup_logger.info("Telegram notify bridge %s", "enabled" if bridge_enabled else "disabled")
            except Exception:
                pass
            # Health notifier (BUS -> Telegram) if enabled
            try:
                from engine.ops.health_notify import HealthNotifier
                import time as _t
                hcfg = {
                    "HEALTH_TG_ENABLED": os.getenv("HEALTH_TG_ENABLED", "true").lower() in {"1","true","yes"},
                    "HEALTH_DEBOUNCE_SEC": int(float(os.getenv("HEALTH_DEBOUNCE_SEC", "10"))),
                }
                HealthNotifier(hcfg, BUS, tg, _startup_logger, _t, metrics)
                _startup_logger.info("Telegram health notifier wired")
            except Exception:
                _startup_logger.warning("Health notifier wiring failed", exc_info=True)
            # Lightweight fills -> Telegram helper (until Alertmanager is in place)
            try:
                async def _on_fill_tele(evt):
                    sym = (evt.get("symbol") or "").upper()
                    side = (evt.get("side") or "").upper()
                    px = float(evt.get("avg_price") or 0.0)
                    qty = float(evt.get("filled_qty") or 0.0)
                    if not sym or px <= 0 or qty <= 0:
                        return
                    BUS.fire("notify.telegram", {"text": f"✅ Fill: *{sym}* {side} qty={qty:.6f} @ `{px}`"})
                BUS.subscribe("trade.fill", _on_fill_tele)
                _startup_logger.info("Telegram fill pings enabled")
            except Exception:
                pass
            try:
                def _on_fill_deck(evt):
                    info = {
                        "order_id": evt.get("order_id"),
                        "filled_qty": evt.get("filled_qty"),
                        "avg_price": evt.get("avg_price"),
                        "venue": evt.get("venue"),
                    }
                    payload = {
                        "ts": float(evt.get("ts") or time.time()),
                        "strategy": (
                            evt.get("strategy_tag")
                            or (evt.get("strategy_meta") or {}).get("name")
                            or evt.get("intent")
                        ),
                        "symbol": evt.get("symbol"),
                        "side": evt.get("side"),
                        "pnl_usd": evt.get("pnl_usd") or evt.get("realized_pnl"),
                        "latency_ms": evt.get("latency_ms"),
                        "info": {k: v for k, v in info.items() if v is not None},
                    }
                    deck_publish_fill({k: v for k, v in payload.items() if v is not None})

                BUS.subscribe("trade.fill", _on_fill_deck)
                _startup_logger.info("Deck fill bridge enabled")
            except Exception:
                _startup_logger.debug("Deck fill bridge wiring failed", exc_info=True)
            roll = EventBORollup()
            # Optional 6h buckets
            buckets = EventBOBuckets(
                bucket_minutes=int(float(os.getenv("DIGEST_6H_BUCKET_MIN", "360"))),
                max_buckets=int(float(os.getenv("DIGEST_6H_MAX_BUCKETS", "4")))
            )
            # Subscribe to event breakout rollup events
            def _subs(bus, fn):
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
    except Exception:
        _startup_logger.warning("Telegram digest failed to start", exc_info=True)

    # Guards: Depeg and Funding
    try:
        if os.getenv("DEPEG_GUARD_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.guards.depeg_guard import DepegGuard
            depeg = DepegGuard(router, bus=BUS, log=_startup_logger)
            async def _loop_depeg():
                while True:
                    try:
                        await depeg.tick()
                        from engine.metrics import risk_depeg_active
                        now = __import__("time").time()
                        val = 1 if now < depeg.safe_until else 0
                        try:
                            risk_depeg_active.set(val)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    await asyncio.sleep(60)
            asyncio.create_task(_loop_depeg())
            _startup_logger.info("Depeg guard started")
    except Exception:
        _startup_logger.warning("Depeg guard wiring failed", exc_info=True)

    try:
        if os.getenv("FUNDING_GUARD_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.guards.funding_guard import FundingGuard
            funding = FundingGuard(router, bus=BUS, log=_startup_logger)
            async def _loop_funding():
                while True:
                    try:
                        await funding.tick()
                    except Exception:
                        pass
                    await asyncio.sleep(300)
            asyncio.create_task(_loop_funding())
            _startup_logger.info("Funding guard started")
    except Exception:
        _startup_logger.warning("Funding guard wiring failed", exc_info=True)

    # Auto cutback/mute overrides (symbol-level execution control)
    try:
        if os.getenv("AUTO_CUTBACK_ENABLED", "").lower() in {"1", "true", "yes"}:
            from engine.execution.venue_overrides import VenueOverrides
            ov = VenueOverrides()
            # Listen to slippage samples and skip events
            BUS.subscribe("event_bo.skip", lambda d: ov.record_skip(d.get("symbol", ""), str(d.get("reason", ""))))
            BUS.subscribe("exec.slippage", lambda d: ov.record_slippage_sample(d.get("symbol", ""), float(d.get("bps", 0.0))))
            # attach to router for place_entry consult
            try:
                setattr(router, "_overrides", ov)
            except Exception:
                pass
            _startup_logger.info("Auto cutback/mute overrides enabled")
    except Exception:
        _startup_logger.warning("Auto cutback wiring failed", exc_info=True)


@app.post("/reconcile/manual")
async def manual_reconciliation():
    """Trigger a manual reconciliation run."""
    try:
        from engine.core.reconcile_daemon import reconcile_once
        stats = await reconcile_once()
        return {"status": "completed", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual reconciliation failed: {e}")


# Startup restoration: load snapshot and best-effort reconcile
def _startup_load_snapshot_and_reconcile():
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
                except Exception:
                    continue
            try:
                _last_position_symbols.clear()
                _last_position_symbols.update(state.positions.keys())
            except Exception:
                pass
            metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)
        except Exception:
            _startup_logger.warning("Failed to hydrate portfolio from snapshot", exc_info=True)
    else:
        _startup_logger.info("No persisted portfolio snapshot found; starting fresh")
    # 2) Best-effort reconcile to catch up with missed fills
    try:
        post_reconcile()  # same logic; small universe should be fast
    except Exception:
        # Non-fatal — engine can still serve, UI can trigger /reconcile manually
        _startup_logger.warning("Initial reconcile on startup failed", exc_info=True)
    # 3) Start strategy scheduler if enabled
    try:
        strategy.start_scheduler()
        _startup_logger.info("Strategy scheduler started")
    except Exception:
        _startup_logger.warning("Strategy scheduler failed to start", exc_info=True)
    try:
        _queue_deck_metrics()
    except Exception:
        pass
    return True


# Run extra startup restoration after startup event
# Initialize strategy hooks
momentum_strategy = None
try:
    if VENUE == "KRAKEN":
        from strategies.momo_15m import Momentum15m
        from engine import strategy as _strategy_mod
        momentum_strategy = Momentum15m(engine=router, symbol="PI_XBTUSD")
        _startup_logger.info("Momentum15m strategy initialized for Kraken")
        base_symbol = momentum_strategy.symbol.split(".")[0]

        def _momentum_listener(sym: str, price: float, ts: float, *, _base=base_symbol, _strategy=momentum_strategy):
            if sym.split(".")[0] == _base:
                _strategy.on_tick(price, ts)

        try:
            _strategy_mod.register_tick_listener(_momentum_listener)
        except Exception:
            _startup_logger.warning("Momentum strategy listener registration failed", exc_info=True)
except Exception:
    _startup_logger.exception("Strategy initialization failed")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _MOMENTUM_BREAKOUT, _LISTING_SNIPER, _MEME_SENTIMENT, _AIRDROP_PROMO, _market_data_logger
    if _market_data_logger is not None:
        try:
            _market_data_logger.stop()
            _startup_logger.info("Market data logger stopped")
        except Exception:
            _startup_logger.debug("Market data logger shutdown encountered issues", exc_info=True)
        _market_data_logger = None
    try:
        if _MOMENTUM_BREAKOUT is not None:
            await _MOMENTUM_BREAKOUT.stop()
            _MOMENTUM_BREAKOUT = None
    except Exception:
        _startup_logger.warning("Momentum breakout shutdown encountered errors", exc_info=True)
    try:
        if _LISTING_SNIPER is not None:
            await _LISTING_SNIPER.shutdown()
    except Exception:
        _startup_logger.warning("Listing sniper shutdown failed", exc_info=True)
    try:
        if _MEME_SENTIMENT is not None:
            from engine.core.event_bus import BUS
            try:
                BUS.unsubscribe("events.external_feed", _MEME_SENTIMENT.on_external_event)
            except Exception:
                pass
            _MEME_SENTIMENT = None
    except Exception:
        _startup_logger.warning("Meme sentiment shutdown failed", exc_info=True)
    try:
        if _AIRDROP_PROMO is not None:
            from engine.core.event_bus import BUS

            try:
                BUS.unsubscribe("events.external_feed", _AIRDROP_PROMO.on_external_event)
            except Exception:
                pass
            try:
                await _AIRDROP_PROMO.shutdown()
            except Exception:
                _startup_logger.warning("Airdrop promo watcher shutdown failed", exc_info=True)
            _AIRDROP_PROMO = None
    except Exception:
        _startup_logger.warning("Airdrop promo shutdown encountered errors", exc_info=True)
    try:
        from engine.core.signal_queue import SIGNAL_QUEUE
        await SIGNAL_QUEUE.stop()
    except Exception:
        pass
    await rest_client.close()


@app.post("/orders/market")
async def submit_market_order(req: MarketOrderRequest, request: Request):
    # Idempotency check
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        cached = CACHE.get(idem_key)
        if cached:
            return JSONResponse(content=cached, status_code=200)

    ok, err = RAILS.check_order(
        symbol=req.symbol,
        side=req.side,  # type: ignore
        quote=req.quote,
        quantity=req.quantity,
        market=(req.market.lower() if isinstance(req.market, str) else req.market),
    )
    if not ok:
        metrics.orders_rejected.inc()
        status = 403 if err.get("error") in {"TRADING_DISABLED", "SYMBOL_NOT_ALLOWED"} else 400
        # Publish risk rejection event
        await publish_risk_event("rejected", {
            "symbol": req.symbol,
            "side": req.side,
            "quote": req.quote,
            "quantity": req.quantity,
            "reason": err.get("error", "UNKNOWN_RISK_VIOLATION"),
            "timestamp": time.time()
        })
        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

    # Apply venue-suffix to symbol if not present, defaulting to request venue or env VENUE
    venue = (req.venue or "").upper() or VENUE
    if "." not in req.symbol:
        req.symbol = f"{req.symbol}.{venue}"

    # ——— Existing execution path (left intact) ———
    try:
        if req.quote is not None:
            result = await router.market_quote(req.symbol, req.side, req.quote, market=(req.market.lower() if isinstance(req.market, str) else None))
        else:
            result = await router.market_quantity(req.symbol, req.side, req.quantity or 0.0, market=(req.market.lower() if isinstance(req.market, str) else None))

        # Store order persistently
        order_id = result.get("id") or str(int(time.time() * 1000))
        if "id" not in result:
            result["id"] = order_id
        if store is not None:
            try:
                _persist_logger.info("Persisting order %s in SQLite", order_id)
                store.insert_order({
                    "id": order_id,
                    "venue": venue.lower(),
                    "symbol": (result.get("symbol") or req.symbol).rsplit(".", 1)[0],
                    "side": req.side,
                    "qty": req.quantity or req.quote,
                    "price": result.get("price") or result.get("avg_fill_price"),
                    "status": "PLACED",
                    "ts_accept": int(time.time() * 1000),
                    "ts_update": int(time.time() * 1000)
                })
                _persist_logger.debug("Order %s stored successfully", order_id)
            except Exception:
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
            market_hint = (result.get("market") or (req.market.lower() if isinstance(req.market, str) else None))
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
                metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)
                # Persist snapshot
                _store.save(state.snapshot())
        except Exception:
            # Non-fatal; reconcile daemon or manual /reconcile can catch up
            pass

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
    except Exception as exc:  # pylint: disable=broad-except
        metrics.orders_rejected.inc()
        _record_venue_error(venue, exc)
        # Surface Binance error payloads for easier debugging
        try:
            if isinstance(exc, _httpx.HTTPStatusError) and exc.response is not None:
                status = exc.response.status_code
                body = exc.response.text
                raise HTTPException(status_code=status, detail=f"Binance error: {body}") from exc
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/orders/limit")
async def submit_limit_order(req: LimitOrderRequest, request: Request):
    # Idempotency check
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        cached = CACHE.get(idem_key)
        if cached:
            return JSONResponse(content=cached, status_code=200)

    ok, err = RAILS.check_order(
        symbol=req.symbol,
        side=req.side,  # type: ignore
        quote=req.quote,
        quantity=req.quantity,
        market=(req.market.lower() if isinstance(req.market, str) else req.market),
    )
    if not ok:
        metrics.orders_rejected.inc()
        status = 403 if err.get("error") in {"TRADING_DISABLED", "SYMBOL_NOT_ALLOWED"} else 400
        await publish_risk_event("rejected", {
            "symbol": req.symbol,
            "side": req.side,
            "quote": req.quote,
            "quantity": req.quantity,
            "reason": err.get("error", "UNKNOWN_RISK_VIOLATION"),
            "timestamp": time.time()
        })
        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

    venue = req.symbol.split(".")[1].upper() if "." in req.symbol else VENUE
    if "." not in req.symbol:
        req.symbol = f"{req.symbol}.{venue}"

    try:
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
                store.insert_order({
                    "id": order_id,
                    "venue": venue.lower(),
                    "symbol": (result.get("symbol") or req.symbol).rsplit(".", 1)[0],
                    "side": req.side,
                    "qty": req.quantity or req.quote,
                    "price": req.price,
                    "status": "PLACED",
                    "ts_accept": int(time.time() * 1000),
                    "ts_update": int(time.time() * 1000)
                })
                _persist_logger.debug("Order %s stored successfully", order_id)
            except Exception:
                _persist_logger.exception("Failed to persist order %s", order_id)

        metrics.orders_submitted.inc()

        # Apply immediate fill (best-effort)
        try:
            raw_symbol = result.get("symbol") or req.symbol
            qty_base = float(result.get("filled_qty_base") or 0.0)
            px = float(result.get("avg_fill_price") or 0.0)
            fee_usd = float(result.get("fee_usd") or 0.0)
            venue_hint = (result.get("venue") or venue).upper()
            market_hint = (result.get("market") or (req.market.lower() if isinstance(req.market, str) else None))
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
        except Exception:
            pass

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
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/symbol_info")
async def symbol_info(symbol: str):
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
    except Exception as exc:
        # Add URL debug info for troubleshooting
        third_party="undefined"
        try:
            import httpx
            if isinstance(exc, httpx.HTTPStatusError):
                third_party = exc.response.url if hasattr(exc.response, 'url') else "no_url"
        except Exception:
            pass
        base_used = settings.api_base or "no_base"
        mode_info = f"mode={settings.mode}, is_futures={settings.is_futures}"
        raise HTTPException(status_code=400,
                             detail=f"symbol_info failed: {exc} ({mode_info}, base_url={base_used}, url_attempted={third_party})")


@app.get("/orders/{order_id}")
def get_order(order_id: str):
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
async def get_portfolio():
    """
    Fast read via router if available, else return last snapshot.
    """
    persisted_snapshot: dict | None = None
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
                    snap["cash_usd"] = float(persisted_snapshot.get("cash_usd"))
                if "equity_usd" not in snap and persisted_snapshot.get("equity_usd") is not None:
                    snap["equity_usd"] = float(persisted_snapshot.get("equity_usd"))
                if not snap.get("positions"):
                    snap["positions"] = list(persisted_snapshot.get("positions", []))
                if not snap.get("pnl") and persisted_snapshot.get("pnl"):
                    snap["pnl"] = dict(persisted_snapshot.get("pnl") or {})
                if "ts_ms" not in snap and persisted_snapshot.get("ts_ms") is not None:
                    snap["ts_ms"] = persisted_snapshot.get("ts_ms")
    except Exception:
        snap = _store.load()
        persisted_snapshot = snap
        if not snap:
            raise HTTPException(status_code=404, detail="No portfolio available")
        snap.setdefault("equity_usd", snap.get("equity"))
        if "equity" not in snap and snap.get("cash_usd") is not None and snap.get("pnl"):
            pnl = snap.get("pnl") or {}
            snap["equity_usd"] = float(snap.get("cash_usd") or 0.0) + float(pnl.get("unrealized", 0.0))
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
            except Exception:
                pass
        snap["quote_ccy"] = QUOTE_CCY
        snap["positions"] = positions
    except Exception:
        pass
    # Refresh engine metrics from latest snapshot so external scrapers see updated values
    try:
        state = portfolio.state
        # Start with current state values; override below for futures
        metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)

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
            g = metrics.REGISTRY.get("pnl_unrealized_symbol")
            for pp in positions2:
                try:
                    qty = float(pp.get("positionAmt", 0) or 0)
                    if abs(qty) <= 0.0:
                        continue
                    sym = str(pp.get("symbol", ""))
                    # Prefer venue-provided unrealizedProfit for mark-based PnL
                    upnl = float(pp.get("unrealizedProfit", 0.0) or 0.0)
                    total_unreal += upnl
                    if g is not None and sym:
                        g.labels(symbol=sym).set(upnl)
                except Exception:
                    continue
            # market_value_usd := total unrealized (not Σ qty*price) for linear futures
            metrics.set_core_metric("market_value_usd", total_unreal)
            # Pull wallet cash directly from the venue snapshot for futures
            cash = 0.0
            if isinstance(snap2, dict):
                try:
                    cash = float(snap2.get("totalWalletBalance") or snap2.get("walletBalance") or 0.0)
                except Exception:
                    cash = float(getattr(state, "cash", 0.0) or 0.0)
            else:
                cash = float(getattr(state, "cash", 0.0) or 0.0)

            # Sync in-process portfolio cash so subsequent calls are consistent
            try:
                portfolio.state.cash = cash
            except Exception:
                pass

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
                        avail = float(snap2.get("availableBalance", snap2.get("maxWithdrawAmount", 0.0)))
                        metrics.set_core_metric("initial_margin_usd", init_m)
                        metrics.set_core_metric("maint_margin_usd", maint_m)
                        metrics.set_core_metric("available_usd", avail)
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            # Spot: signed market value = sum(qty * last)
            try:
                mv = sum(pos.quantity * pos.last_price for pos in state.positions.values())
                metrics.set_core_metric("market_value_usd", mv)
                # Per-symbol unrealized for invariants derived from in-process state
                g = metrics.REGISTRY.get("pnl_unrealized_symbol")
                if g is not None:
                    for pos in state.positions.values():
                        g.labels(symbol=pos.symbol).set(pos.upl)
            except Exception:
                pass
        # Record mark time for auditability - always set, even when no positions
        try:
            metrics.set_core_metric("mark_time_epoch", time.time())
        except Exception:
            pass
    except Exception:
        pass
    try:
        state = portfolio.state
        snap.setdefault("cash_usd", float(getattr(state, "cash", 0.0)))
        snap.setdefault("equity_usd", float(getattr(state, "equity", 0.0)))
        pnl = snap.get("pnl") or {}
        pnl.setdefault("realized", float(getattr(state, "realized", 0.0)))
        pnl.setdefault("unrealized", float(getattr(state, "unrealized", 0.0)))
        snap["pnl"] = pnl
    except Exception:
        pass

    if "cash_usd" not in snap or "equity_usd" not in snap:
        fallback = persisted_snapshot or _store.load() or {}
        if "cash_usd" not in snap and fallback.get("cash_usd") is not None:
            snap["cash_usd"] = float(fallback.get("cash_usd"))
        if "equity_usd" not in snap:
            if fallback.get("equity_usd") is not None:
                snap["equity_usd"] = float(fallback.get("equity_usd"))
            elif snap.get("equity") is not None:
                snap["equity_usd"] = float(snap.get("equity"))
            else:
                pnl = snap.get("pnl") or {}
                snap["equity_usd"] = float(snap.get("cash_usd") or 0.0) + float(pnl.get("unrealized", 0.0))
    return snap


@app.get("/account_snapshot")
async def account_snapshot(force: bool = False):
    """
    Return account snapshot. If force=1, pull a fresh snapshot from the venue
    and update router cache + snapshot_loaded flag immediately.
    """
    snap = await (router.fetch_account_snapshot() if force else router.get_account_snapshot())

    try:
        router.snapshot_loaded = True
    except Exception:
        pass

    if VENUE == "KRAKEN":
        try:
            await rest_client.refresh_portfolio()
        except Exception as exc:
            _persist_logger.warning("Failed to refresh Kraken portfolio: %s", exc)

    state = portfolio.state
    try:
        metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)
        metrics.set_core_metric("equity_usd", float(state.equity))
        metrics.set_core_metric("available_usd", float(snap.get("availableBalance", state.cash)))
        metrics.set_core_metric("mark_time_epoch", time.time())
    except Exception:
        pass

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
            equity_val = float(getattr(state, "equity", cash_val + unreal_val) or (cash_val + unreal_val))
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
        except Exception:
            _persist_logger.exception("Failed to persist account snapshot for venue %s", VENUE.lower())
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
            metrics.set_core_symbol_metric("mark_price", symbol=key, value=float(position.last_price))
    try:
        stale = _last_position_symbols - current_symbols
        for sym in stale:
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
        _last_position_symbols.clear()
        _last_position_symbols.update(current_symbols)
    except Exception:
        pass
    try:
        _store.save(state.snapshot())
    except Exception:
        pass
    try:
        _queue_deck_metrics()
    except Exception:
        pass
    return snap


@app.post("/account_snapshot/refresh")
async def account_snapshot_refresh():
    """Force-refresh the venue snapshot and update gauges."""
    return await account_snapshot(force=True)


@app.post("/reconcile")
def post_reconcile():
    """
    Fetch fills since last snapshot and apply. Runs in the request thread for simplicity;
    you can move to background if reconciliation might be slow.
    """
    # Symbols: prefer TRADE_SYMBOLS allowlist; fallback to router universe
    symbols = (risk_cfg.trade_symbols or [])
    if not symbols:
        try:
            symbols = router.trade_symbols()  # EXPECTED: provide in router
        except Exception:
            symbols = []
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols configured for reconciliation")

    try:
        snap = reconcile_since_snapshot(
            portfolio=router.portfolio_service(),   # EXPECTED: provide in router
            client=router.exchange_client(),        # EXPECTED: provide in router
            symbols=[s if s.endswith("USDT") else f"{s}USDT" for s in symbols],
        )
        _boot_status["reconciled"] = True
        global _last_reconcile_ts
        _last_reconcile_ts = time.time()
        metrics.reconcile_lag_seconds.set(0.0)
        try:
            _queue_deck_metrics()
        except Exception:
            pass
        return {"status": "ok", "applied_snapshot_ts_ms": snap.get("ts_ms"), "equity": snap.get("equity_usd")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconcile failed: {e}")


@app.on_event("startup")
async def _bootstrap_snapshot_state():
    """Restore snapshot + reconcile in background to avoid blocking server startup."""
    try:
        await asyncio.to_thread(_startup_load_snapshot_and_reconcile)
    except Exception:
        _startup_logger.warning("Snapshot bootstrap failed", exc_info=True)


@app.get("/health")
async def health():
    try:
        snap = _store.load() or {}
    except Exception:
        snap = {}
    lag = max(0.0, time.time() - _last_reconcile_ts) if _last_reconcile_ts else None
    if lag is not None:
        metrics.reconcile_lag_seconds.set(lag)
    # Update snapshot_loaded gauge for alerting - derive truth from router state
    snap_ok = bool(getattr(router, "snapshot_loaded", False))
    try:
        metrics.REGISTRY["snapshot_loaded"].set(1 if snap_ok else 0)
    except Exception:
        pass

    # Venue-specific labels for health endpoint
    venue = VENUE.lower()
    if venue == "kraken":
        equity_source = "derivatives/api/v3/accounts.totalMarginValue"
        upnl_source = "derivatives/api/v3/openpositions.unrealizedProfit"
        price_source = "tickers.last | markPrice | bid/ask"
        wallet_source = "derivatives/api/v3/accounts.cashBalance"
    else:
        # Binance (default)
        equity_source = "fapi/v2/account.totalMarginBalance"
        upnl_source = "positionRisk.sum(unRealizedProfit)"
        price_source = "mark_price/premiumIndex"
        wallet_source = "fapi/v2/account.totalWalletBalance"

    # Include symbols if unrestricted
    from engine.config import load_risk_config
    risk_cfg = load_risk_config()
    symbols = None
    if risk_cfg.trade_symbols is None:
        try:
            from engine.universe import configured_universe
            symbols = configured_universe()
        except Exception:
            pass

    try:
        metrics.MARK_PRICE.labels(symbol=base, venue="kraken").set(0.0)
        metrics.mark_price_by_symbol.labels(symbol=base).set(0.0)
    except Exception:
        pass

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
def get_universe():
    """Return configured trading symbols in BASEQUOTE (no venue suffix)."""
    return {"symbols": configured_universe(), "quote_ccy": QUOTE_CCY}


@app.get("/prices")
async def get_prices():
    """Return last trade/mark prices for current universe."""
    return {"prices": await last_prices(), "ts": time.time(), "quote_ccy": QUOTE_CCY}

@app.post("/strategy/promote")
async def promote_strategy(request: Request):
    """Hot-swap to a new strategy model at runtime."""
    import os
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON body required: {\"model_tag\": \"<tag>\"}")
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
        if hasattr(strategy, 'reload_model'):
            await strategy.reload_model(tag)
    except AttributeError:
        pass  # Strategy layer doesn't support hot reload, that's ok
    except Exception as exc:
        # Surface reload errors clearly to caller
        raise HTTPException(status_code=500, detail=f"reload_model failed: {exc}")

    return {"message": f"Strategy switched to {tag}", "model_tag": tag}


@app.get("/stream")
async def sse_stream():
    """Server-Sent Events endpoint for real-time engine updates."""
    async def event_generator():
        """Generate SSE events for live UI updates."""
        queue = asyncio.Queue()
        handlers = {}  # Keep references to prevent garbage collection

        def queue_event(topic: str, data: dict):
            queue.put_nowait((topic, data))

        # Subscribe to key event topics
        topics = ["order.submitted", "order.filled", "order.closed", "risk.rejected",
                 "metrics.update", "strategy.promoted", "reconcile.completed"]

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
async def _start_external_feeds():
    """Launch external data feed connectors described in YAML config."""
    if IS_EXPORTER:
        return
    try:
        from engine.feeds.external_connectors import spawn_external_feeds_from_config
        started = await spawn_external_feeds_from_config()
        if started:
            _startup_logger.info("External feed connectors started: %s", ", ".join(started))
    except Exception:
        _startup_logger.warning("External feed connectors failed to start", exc_info=True)


@app.on_event("startup")
async def _start_event_bus():
    """Initialize the real-time event bus."""
    if IS_EXPORTER:
        return
    try:
        await initialize_event_bus()
        _startup_logger.info("Event bus started")
        from engine.core.signal_queue import SIGNAL_QUEUE

        SIGNAL_QUEUE.start(BUS)
        _startup_logger.info("Signal priority queue dispatcher online")
        if not DECK_PUSH_DISABLED:
            BUS.subscribe("trade.fill", _deck_fill_handler)
            _deck_logger.info("Deck fill bridge subscribed to trade.fill")
    except Exception:
        _startup_logger.exception("Event bus startup failed")


@app.on_event("startup")
async def _start_deck_metrics():
    """Launch background loop that pushes live metrics to the Deck."""
    if IS_EXPORTER or DECK_PUSH_DISABLED:
        return
    global _deck_metrics_task
    if _deck_metrics_task and not _deck_metrics_task.done():
        return
    _deck_metrics_task = asyncio.create_task(_deck_metrics_loop(), name="deck-metrics")
    _deck_logger.info("Deck metrics loop started (interval=%.1fs)", DECK_METRICS_INTERVAL_SEC)


@app.on_event("shutdown")
async def _stop_deck_metrics():
    """Stop Deck metrics loop on shutdown."""
    global _deck_metrics_task
    if not _deck_metrics_task:
        return
    _deck_metrics_task.cancel()
    with suppress(asyncio.CancelledError):
        await _deck_metrics_task
    _deck_metrics_task = None


@app.on_event("startup")
async def _start_alerting():
    """Initialize the real-time alerting system."""
    if IS_EXPORTER:
        return
    try:
        await alert_daemon.initialize_alerting()
        _startup_logger.info("Alerting system started")
    except Exception:
        _startup_logger.exception("Alerting startup failed")


@app.on_event("startup")
async def _start_governance():
    """Initialize the autonomous governance system - the final layer!"""
    if IS_EXPORTER:
        return
    try:
        from ops import governance_daemon
        await governance_daemon.initialize_governance()
        _startup_logger.info("Autonomous governance activated")
    except Exception:
        _startup_logger.exception("Governance startup failed")


@app.on_event("startup")
async def _start_bracket_governor():
    if IS_EXPORTER:
        return
    try:
        if os.getenv("BRACKET_GOVERNOR_ENABLED", "true").lower() in {"1","true","yes"}:
            BracketGovernor(router, BUS, _startup_logger).wire()
    except Exception:
        _startup_logger.warning("Bracket governor wiring failed", exc_info=True)


@app.on_event("startup")
async def _start_stop_validator() -> None:
    global _stop_validator
    if IS_EXPORTER:
        return
    enabled = os.getenv("STOP_VALIDATOR_ENABLED", "true").lower() in {"1", "true", "yes"}
    if not enabled:
        return
    cfg = {
        "STOP_VALIDATOR_ENABLED": enabled,
        "STOP_VALIDATOR_REPAIR": os.getenv("STOP_VALIDATOR_REPAIR", "true").lower() in {"1", "true", "yes"},
        "STOP_VALIDATOR_GRACE_SEC": float(os.getenv("STOP_VALIDATOR_GRACE_SEC", "2")),
        "STOP_VALIDATOR_INTERVAL_SEC": float(os.getenv("STOP_VALIDATOR_INTERVAL_SEC", "5")),
        "STOPVAL_NOTIFY_ENABLED": os.getenv("STOPVAL_NOTIFY_ENABLED", "false").lower() in {"1", "true", "yes"},
        "STOPVAL_NOTIFY_DEBOUNCE_SEC": float(os.getenv("STOPVAL_NOTIFY_DEBOUNCE_SEC", "60")),
    }
    try:
        md = _MDAdapter(router)
        _stop_validator = StopValidator(cfg, router, md, log=_startup_logger, metrics=metrics, bus=BUS)
        asyncio.create_task(_stop_validator.run())
        _startup_logger.info("Stop Validator started (repair=%s)", cfg["STOP_VALIDATOR_REPAIR"])
    except Exception:
        _startup_logger.warning("Stop Validator startup failed", exc_info=True)


@app.on_event("startup")
async def _subscribe_governance_hooks():
    """React to governance actions by hot-reloading risk rails."""
    if IS_EXPORTER:
        return
    async def _on_governance_action(_data: dict) -> None:
        # Governance mutated runtime env vars; reflect into risk rails config
        from engine.config import load_risk_config
    try:
        RAILS.cfg = load_risk_config()
        metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
        try:
            metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
        except Exception:
            pass
    except Exception:
        pass

    try:
        BUS.subscribe("governance.action", _on_governance_action)
    except Exception:
        pass


async def _refresh_binance_futures_snapshot() -> None:
    """Single refresh tick for Binance futures accounts."""
    global _price_map, _basis_cache, _snapshot_counter

    try:
        _refresh_logger.debug("refresh tick")
    except Exception:
        pass

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
                except Exception:
                    px = 0.0
                if px <= 0.0:
                    continue
                new_map[sym] = px
                try:
                    metrics.MARK_PRICE.labels(symbol=sym, venue="binance").set(px)
                except Exception:
                    pass
                _maybe_emit_strategy_tick(sym, px, ts=now_ts, source="rest_snapshot", stream="rest")
            if new_map:
                _price_map = new_map
    except Exception:
        pass

    try:
        acc_data = await rest_client.account()
    except Exception:
        acc_data = {}
    if acc_data:
        try:
            wallet = float(acc_data.get("totalWalletBalance", 0.0))
            upnl = float(acc_data.get("totalUnrealizedProfit", 0.0))
            equity = float(acc_data.get("totalMarginBalance", 0.0))
        except Exception:
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
        except Exception:
            pass

    try:
        pos_data = await rest_client.position_risk()
    except Exception:
        pos_data = []
    pos_data = [p for p in pos_data if float(p.get("positionAmt", 0.0)) != 0.0]

    is_hedge = False
    try:
        is_hedge = await rest_client.hedge_mode()
    except Exception:
        is_hedge = False

    if is_hedge:
        legs = [p for p in pos_data if p.get("positionSide") in ("LONG", "SHORT")]
    else:
        legs = [p for p in pos_data if p.get("positionSide", "BOTH") == "BOTH"]

    if legs:
        try:
            upnl_total = sum(float(p.get("unRealizedProfit", 0.0)) for p in legs)
            metrics.set_core_metric("market_value_usd", upnl_total)
        except Exception:
            pass

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
            except Exception:
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
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=float(agg.get("amt", 0.0)))
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=float(agg.get("entry", 0.0)))
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=float(agg.get("upnl", 0.0)))
            mark = 0.0
            if isinstance(_price_map, dict):
                try:
                    raw_mark = _price_map.get(sym, 0.0)
                    if isinstance(raw_mark, dict):
                        mark = float(raw_mark.get("markPrice", 0.0) or 0.0)
                    else:
                        mark = float(raw_mark or 0.0)
                except Exception:
                    mark = 0.0
            if mark:
                metrics.set_core_symbol_metric("mark_price", symbol=sym, value=mark)
                try:
                    metrics.MARK_PRICE.labels(symbol=sym, venue="binance").set(mark)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        stale = _last_position_symbols - current_symbols
        for sym in stale:
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
        _last_position_symbols.clear()
        _last_position_symbols.update(current_symbols)
    except Exception:
        pass

    now_ts = time.time()
    metrics.set_core_metric("mark_time_epoch", now_ts)
    metrics.set_core_metric("metrics_heartbeat", now_ts)
    _snapshot_counter += 1
    metrics.set_core_metric("snapshot_id", _snapshot_counter)
    try:
        _queue_deck_metrics()
    except Exception:
        pass


async def _refresh_binance_spot_snapshot() -> None:
    """Single refresh tick tailored for Binance spot accounts."""
    global _price_map, _basis_cache, _snapshot_counter

    symbol_filter: set[str] = set()
    try:
        raw_symbols = await asyncio.to_thread(configured_universe)
        symbol_filter = {s.split(".")[0].upper() for s in raw_symbols}
    except Exception:
        symbol_filter = set()

    try:
        base = (settings.spot_base or settings.api_base or "").rstrip("/") or "https://api.binance.com"
        async with _httpx.AsyncClient(base_url=base, timeout=settings.timeout) as client:
            resp = await client.get("/api/v3/ticker/price")
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
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
            except Exception:
                continue
            if px > 0:
                new_map[sym] = px
                _maybe_emit_strategy_tick(sym, px, source="rest_snapshot", stream="rest")
        if new_map:
            _price_map = new_map
            for sym, px in new_map.items():
                try:
                    metrics.MARK_PRICE.labels(symbol=sym, venue="binance").set(px)
                except Exception:
                    continue

    try:
        account = await rest_client.account_snapshot()
    except Exception:
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
                except Exception:
                    free = locked = 0.0
                wallet = free + locked
                break

    state = portfolio.state
    try:
        state.cash = wallet
    except Exception:
        pass

    unreal = float(getattr(state, "unrealized", 0.0) or 0.0)
    equity = wallet + unreal
    try:
        state.equity = equity
    except Exception:
        pass

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
            metrics.set_core_symbol_metric("entry_price", symbol=base_sym, value=float(getattr(position, "avg_price", 0.0) or 0.0))
            metrics.set_core_symbol_metric("unrealized_profit", symbol=base_sym, value=float(getattr(position, "upl", 0.0) or 0.0))
            mark = 0.0
            if isinstance(_price_map, dict):
                try:
                    raw_mark = _price_map.get(base_sym, 0.0)
                    if isinstance(raw_mark, dict):
                        mark = float(raw_mark.get("markPrice", 0.0) or 0.0)
                    else:
                        mark = float(raw_mark or 0.0)
                except Exception:
                    mark = 0.0
            if mark:
                metrics.set_core_symbol_metric("mark_price", symbol=base_sym, value=mark)
                try:
                    metrics.MARK_PRICE.labels(symbol=base_sym, venue="binance").set(mark)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        stale = _last_position_symbols - current_symbols
        for sym in stale:
            metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
            metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
        _last_position_symbols.clear()
        _last_position_symbols.update(current_symbols)
    except Exception:
        pass

    metrics.set_core_metric("mark_time_epoch", now_ts)
    metrics.set_core_metric("metrics_heartbeat", now_ts)
    _snapshot_counter += 1
    metrics.set_core_metric("snapshot_id", _snapshot_counter)
    try:
        _queue_deck_metrics()
    except Exception:
        pass


async def _refresh_venue_data():
    """Background task to refresh price map, basis cache, and account totals from venue."""
    global _price_map, _basis_cache, _snapshot_counter

    if VENUE != "BINANCE":
        return

    try:
        _refresh_logger.info("Starting venue refresh loop (pid=%s, venue=%s, futures=%s)", os.getpid(), VENUE, settings.is_futures)
    except Exception:
        pass

    while True:
        try:
            if settings.is_futures:
                await _refresh_binance_futures_snapshot()
            else:
                await _refresh_binance_spot_snapshot()
        except Exception:
            try:
                _refresh_logger.exception("refresh loop error")
            except Exception:
                pass
        await asyncio.sleep(5)


async def _kraken_risk_metrics_loop() -> None:
    base_interval = max(_safe_float(os.getenv("KRAKEN_RISK_INTERVAL_SEC")) or 5.0, 3.0)
    min_interval = base_interval
    max_interval = max(30.0, base_interval * 6.0)
    backoff_factor = 2.0
    jitter_pct = 0.2
    interval = base_interval
    failure_streak = 0
    last_snapshot: dict[str, Any] | None = None

    _kraken_risk_stop_event.clear()

    # Prewarm gauges for Grafana legends
    try:
        cap_val = max(0.0, float(RAILS.cfg.exposure_cap_venue_usd))
        metrics.venue_exposure_usd.labels(venue="kraken").set(0.0)
        metrics.exposure_cap_usd.labels(venue="kraken").set(cap_val)
        metrics.risk_exposure_headroom_usd.labels(venue="kraken").set(cap_val)
        metrics.kraken_equity_usd.set(0.0)
        metrics.kraken_unrealized_usd.set(0.0)
        metrics.kraken_equity_drawdown_pct.set(0.0)
        metrics.risk_metrics_freshness_sec.set(0.0)
        for product in _KRAKEN_PRODUCTS or ["PI_XBTUSD"]:
            try:
                metrics.mark_price_freshness_sec.labels(symbol=product, venue="kraken").set(float("inf"))
            except Exception:
                pass
    except Exception:
        pass

    while True:
        tick_start = time.monotonic()
        snapshot: dict[str, Any] | None = None
        try:
            snapshot = await router.get_account_snapshot()
            if snapshot:
                last_snapshot = snapshot
                failure_streak = 0
                if interval > base_interval:
                    interval = max(base_interval, interval / backoff_factor)
        except Exception as exc:
            failure_streak += 1
            interval = min(max_interval, max(min_interval, interval * backoff_factor))
            _kraken_risk_logger.warning("Kraken snapshot fetch failed (streak=%s): %s", failure_streak, exc)
            snapshot = last_snapshot

        if snapshot is None:
            try:
                snapshot = router.portfolio_snapshot()
            except Exception:
                snapshot = None

        snap_dict = snapshot if isinstance(snapshot, dict) else None

        if snap_dict is not None:
            try:
                RAILS.refresh_snapshot_metrics(snap_dict, venue="kraken")

                equity_val = _safe_float(snap_dict.get("equity_usd") or snap_dict.get("equity"))
                if equity_val is not None:
                    metrics.kraken_equity_usd.set(equity_val)
                    drawdown_pct = RAILS._compute_drawdown_pct(equity_val)  # type: ignore[attr-defined]
                    metrics.kraken_equity_drawdown_pct.set(max(0.0, drawdown_pct))

                pnl_raw = snap_dict.get("pnl")
                pnl_section = pnl_raw if isinstance(pnl_raw, dict) else {}
                unreal_val = _safe_float(pnl_section.get("unrealized")) or 0.0
                metrics.kraken_unrealized_usd.set(unreal_val)

                positions = snap_dict.get("positions")
                if isinstance(positions, list):
                    now_ts = time.time()
                    for pos in positions:
                        try:
                            sym_raw = pos.get("symbol") or ""
                            base = _kraken_symbol_base(sym_raw)
                            last_px = pos.get("last_price_quote")
                            if last_px is None:
                                last_px = await _kraken_safe_price(base)
                            if isinstance(last_px, (int, float)) and last_px > 0.0:
                                _kraken_record_mark(base, float(last_px), now_ts)
                        except Exception:
                            continue

                snap_ts = None
                raw_ts = snap_dict.get("ts")
                raw_ts_ms = snap_dict.get("ts_ms")
                if isinstance(raw_ts, (int, float)) and math.isfinite(float(raw_ts)):
                    snap_ts = float(raw_ts)
                elif isinstance(raw_ts_ms, (int, float)) and math.isfinite(float(raw_ts_ms)):
                    snap_ts = float(raw_ts_ms) / 1000.0
                freshness = max(0.0, time.time() - snap_ts) if snap_ts is not None else 0.0
                metrics.risk_metrics_freshness_sec.set(freshness)
            except Exception:
                _kraken_risk_logger.exception("Failed to update Kraken risk telemetry")
        else:
            try:
                metrics.risk_metrics_freshness_sec.set(float("inf"))
            except Exception:
                pass

        if VENUE == "KRAKEN":
            await _kraken_refresh_mark_prices(time.time())

        try:
            _queue_deck_metrics()
        except Exception:
            pass

        elapsed = time.monotonic() - tick_start
        sleep_base = max(0.5, interval - elapsed)
        jitter = random.uniform(1.0 - jitter_pct, 1.0 + jitter_pct)
        sleep_for = max(0.5, sleep_base) * jitter

        if _kraken_risk_stop_event.is_set():
            break

        try:
            await asyncio.wait_for(_kraken_risk_stop_event.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            _kraken_risk_logger.exception("Kraken telemetry wait interrupted")

        if _kraken_risk_stop_event.is_set():
            break


@app.on_event("startup")
async def _start_kraken_ws():
    """Start Kraken WebSocket price feeds for real-time pricing."""
    if VENUE == "KRAKEN":
        try:
            from engine.core.kraken_ws import KrakenWS
            products = _KRAKEN_PRODUCTS or ["PI_XBTUSD"]
            from engine import strategy as _strategy_mod

            ws = KrakenWS(
                products=products,
                portfolio=portfolio,
                on_price_cb=_strategy_mod.on_tick,
                rest_client=rest_client,
                price_hook=_kraken_on_mark,
            )
            asyncio.create_task(ws.run())  # fire-and-forget
            _startup_logger.info("Kraken websocket price feeds started for products=%s (role=%s)", products, ROLE)
        except Exception:
            _startup_logger.exception("Kraken websocket startup failed")


@app.on_event("startup")
async def _start_venue_refresh():
    """Start background venue data refresh."""
    if VENUE != "BINANCE":
        return
    base_url = settings.api_base or "default"
    role = "exporter" if IS_EXPORTER else "trader"
    _refresh_logger.info(
        "Starting background refresh task venue=%s mode=%s base=%s pid=%s role=%s",
        VENUE,
        settings.mode,
        base_url,
        os.getpid(),
        role,
    )
    asyncio.create_task(_refresh_venue_data())


@app.on_event("startup")
async def _start_binance_ws():
    if VENUE != "BINANCE":
        return
    # Feature flag
    if os.getenv("BINANCE_WS_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return
    # Determine WS base URL
    if settings.is_futures:
        if "test" in (settings.mode or ""):
            ws_base = "wss://stream.binancefuture.com/stream"
        else:
            ws_base = "wss://fstream.binance.com/stream"
    else:
        if (settings.mode or "").startswith("demo") or "test" in (settings.mode or ""):
            ws_base = "wss://testnet.binance.vision/stream"
        else:
            ws_base = "wss://stream.binance.com:9443/stream"

    # Select symbols: prefer configured allowlist; else a small default set
    try:
        allowed = configured_universe()
        bases = [s.split(".")[0].upper() for s in allowed][:100] if allowed else []
    except Exception:
        bases = []
    if not bases:
        bases = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

    role = "exporter" if IS_EXPORTER else "trader"
    try:
        from engine import strategy as _strategy_mod
        on_cb = None if IS_EXPORTER else None
        stream_mode = os.getenv("BINANCE_WS_STREAM", "auto").lower()
        scalper_module = getattr(_strategy_mod, "SCALP_MODULE", None)
        if stream_mode == "auto":
            if settings.is_futures:
                stream_mode = "mark"
            elif scalper_module and getattr(scalper_module, "enabled", False):
                stream_mode = os.getenv("SCALP_WS_STREAM", "aggtrade").lower()
            else:
                stream_mode = "miniticker"
        global _market_data_dispatcher
        if _market_data_dispatcher is None:
            _market_data_dispatcher = MarketDataDispatcher(BUS, source="binance_ws", venue="BINANCE")
        ws = BinanceWS(
            symbols=bases,
            url_base=ws_base,
            is_futures=settings.is_futures,
            role=role,
            on_price_cb=on_cb,
            price_hook=_binance_on_mark,
            stream_type=stream_mode,
            event_callback=_market_data_dispatcher.handle_stream_event,
        )
        asyncio.create_task(ws.run())
        # remember symbols for freshness loop
        global _BINANCE_WS_SYMBOLS
        _BINANCE_WS_SYMBOLS = list(bases)
        _startup_logger.warning("Binance WS started (%s, futures=%s, symbols=%d, ws_base=%s)", role, settings.is_futures, len(bases), ws_base)
    except Exception:
        _startup_logger.warning("Binance WS failed to start", exc_info=True)


@app.on_event("startup")
async def _start_market_data_logger() -> None:
    if os.getenv("MARKET_DATA_LOGGER", "false").lower() not in {"1", "true", "yes"}:
        return
    global _market_data_logger
    if _market_data_logger is not None:
        return
    try:
        rate = float(os.getenv("MARKET_DATA_LOGGER_RATE", "5.0"))
    except (TypeError, ValueError):
        rate = 5.0
    try:
        _market_data_logger = MarketDataLogger(BUS, sample_rate_hz=rate)
        _market_data_logger.start()
        _startup_logger.info("Market data logger subscribed (rate=%.2f Hz)", rate)
    except Exception:
        _startup_logger.warning("Market data logger failed to start", exc_info=True)


@app.on_event("startup")
async def _start_binance_ws_freshness() -> None:
    if VENUE != "BINANCE":
        return
    if os.getenv("BINANCE_WS_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return
    async def loop():
        while True:
            now = time.time()
            try:
                for base in list(_BINANCE_WS_SYMBOLS) or []:
                    last_ts = _binance_mark_ts.get(base)
                    freshness = float("inf") if last_ts is None else max(0.0, now - last_ts)
                    try:
                        metrics.mark_price_freshness_sec.labels(symbol=base, venue="binance").set(freshness)
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(5)
    try:
        asyncio.create_task(loop())
    except Exception:
        pass


@app.on_event("startup")
async def _start_kraken_risk_loop():
    if VENUE != "KRAKEN" or IS_EXPORTER:
        return
    global _kraken_risk_loop_task
    if _kraken_risk_loop_task and not _kraken_risk_loop_task.done():
        return
    _kraken_risk_loop_task = asyncio.create_task(_kraken_risk_metrics_loop())
    _kraken_risk_logger.info("Kraken risk telemetry loop scheduled")


@app.on_event("shutdown")
async def _stop_kraken_risk_loop():
    global _kraken_risk_loop_task
    if _kraken_risk_loop_task is None:
        return
    _kraken_risk_stop_event.set()
    _kraken_risk_loop_task.cancel()
    try:
        await _kraken_risk_loop_task
    except asyncio.CancelledError:
        pass
    except Exception:
        _kraken_risk_logger.exception("Kraken telemetry loop shutdown error")
    finally:
        _kraken_risk_loop_task = None


@app.on_event("startup")
def _init_prom_multiproc_dir():
    """Ensure PROMETHEUS_MULTIPROC_DIR exists and clear stale DBs on each worker boot."""
    try:
        import os
        import pathlib

        mp = os.getenv("PROMETHEUS_MULTIPROC_DIR", "/tmp/prom_multiproc")
        path = pathlib.Path(mp)
        path.mkdir(parents=True, exist_ok=True)

        for f in path.glob("*.db"):
            try:
                f.unlink()
            except FileNotFoundError:
                continue
            except Exception:
                pass
        try:
            _startup_logger.info("Prometheus multiprocess directory: %s", path)
        except Exception:
            pass
    except Exception:
        pass


@app.get("/events/stats")
def get_event_stats():
    """Get event bus statistics."""
    return {"event_bus": BUS.get_stats() if hasattr(BUS, 'get_stats') else {}}


@app.get("/alerts/stats")
def get_alert_stats():
    """Get alerting system statistics."""
    return {"alerting": alert_daemon._alert_daemon.get_stats() if alert_daemon._alert_daemon else {}}


@app.get("/limits")
def get_limits():
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
def get_risk_config():
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
def reload_risk_config():
    """Hot-reload risk configuration from environment variables."""
    from engine.config import load_risk_config
    RAILS.cfg = load_risk_config()
    metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
    try:
        metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
    except Exception:
        pass
    cfg = RAILS.cfg
    return {
        "status": "ok",
        "trading_enabled": cfg.trading_enabled,
        "min_notional_usdt": cfg.min_notional_usdt,
        "max_notional_usdt": cfg.max_notional_usdt,
        "max_orders_per_min": cfg.max_orders_per_min,
    }


@app.get("/governance/status")
def get_governance_status():
    """Get autonomous governance system status."""
    try:
        from ops import governance_daemon
        return {"governance": governance_daemon.get_governance_status()}
    except Exception as e:
        return {"governance": {"status": "error", "error": str(e)}}


@app.post("/governance/reload")
def reload_governance_policies():
    """Hot-reload governance policies."""
    try:
        from ops import governance_daemon
        success = governance_daemon.reload_governance_policies()
        return {"status": "success" if success else "failed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/governance/actions")
def list_governance_actions(limit: int = 20):
    """Return the most recent governance actions (audit log)."""
    try:
        from ops import governance_daemon
        actions = governance_daemon.get_recent_governance_actions(limit)
        return {"actions": actions, "limit": limit}
    except Exception as e:
        return {"actions": [], "error": str(e)}


@app.post("/governance/simulate/{event_type}")
async def simulate_governance_event(event_type: str):
    """Simulate governance triggers for testing."""
    # Simulate different types of events that would trigger governance
    test_events = {
        "poor_performance": {
            "pnl_unrealized": -150.0,
            "sharpe": 0.05,
            "equity_usd": 9850.0
        },
        "great_performance": {
            "pnl_unrealized": 120.0,
            "sharpe": 2.5,
            "equity_usd": 10120.0
        },
        "risk_breach": {
            "symbol": "BTCUSDT.BINANCE",
            "side": "BUY",
            "reason": "EXPOSURE_LIMIT"
        },
        "market_stress": {
            "spread_pct": 0.03,
            "volatility_spike": True
        }
    }

    if event_type in test_events:
        try:
            # Publish test event to trigger governance
            if event_type == "poor_performance":
                await BUS.publish("metrics.update", test_events[event_type])
            elif event_type == "great_performance":
                await BUS.publish("metrics.update", test_events[event_type])
            elif event_type == "risk_breach":
                await BUS.publish("risk.rejected", test_events[event_type])
            elif event_type == "market_stress":
                await BUS.publish("price.anomaly", test_events[event_type])

            return {"status": f"simulated {event_type}", "data": test_events[event_type]}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        return {"status": "error", "message": f"Unknown event type: {event_type}"}
