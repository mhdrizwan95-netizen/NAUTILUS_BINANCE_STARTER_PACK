from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional

from ..core import order_router
from ..core.market_resolver import resolve_market
from ..core.portfolio import Portfolio
from ..metrics import (
    leverage_set_latency_ms,
    strategy_bucket_usage_fraction,
    strategy_leverage_applied,
    strategy_leverage_configured,
    strategy_leverage_mismatch_total,
    strategy_orders_total,
    strategy_signal_latency_seconds,
    strategy_signal_queue_latency_sec,
    strategy_signal_queue_len,
    strategy_signals_total,
)
from .config import RuntimeConfig
from .universe import UniverseManager

log = logging.getLogger("engine.runtime.pipeline")


@dataclass(frozen=True)
class Signal:
    strategy: str
    symbol: str
    side: str
    confidence: float
    venue_hint: Optional[str] = None
    stop: Optional[float] = None
    take_profit: Optional[float] = None
    ttl: Optional[float] = None
    meta: Dict[str, float | str] = field(default_factory=dict)

    def normalized_strategy(self) -> str:
        return self.strategy.lower()


@dataclass
class ExecutionOrder:
    strategy: str
    symbol: str
    side: str
    venue: str
    notional_usd: float
    notional_fraction: float
    bucket: str
    quantity: float = 0.0
    leverage: Optional[int] = None
    configured_leverage: Optional[int] = None
    applied_leverage: Optional[int] = None
    effective_leverage: int = 1
    margin_fraction: float = 0.0
    reduce_only: bool = False
    stop: Optional[float] = None
    take_profit: Optional[float] = None
    client_order_id: str = field(default_factory=lambda: f"runtime:{uuid.uuid4().hex[:18]}")


class StrategyProducer:
    """
    Base contract for async signal producers. Concrete implementations should
    override :meth:`run` and push :class:`Signal` objects onto the shared queue.
    """

    name: str

    def __init__(self, name: str) -> None:
        self.name = name
        self._running = False

    async def run(self, bus: asyncio.Queue[tuple[Signal, float]], config: RuntimeConfig) -> None:
        raise NotImplementedError

    async def _publish(self, bus: asyncio.Queue, signal: Signal) -> None:
        await bus.put((signal, time.time()))


class StrategyRegistry:
    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[RuntimeConfig, UniverseManager], StrategyProducer]] = (
            {}
        )

    def register(
        self,
        name: str,
        factory: Callable[[RuntimeConfig, UniverseManager], StrategyProducer],
    ) -> None:
        key = name.lower()
        self._factories[key] = factory

    def build_all(
        self, config: RuntimeConfig, manager: UniverseManager
    ) -> Iterable[StrategyProducer]:
        for key, factory in self._factories.items():
            try:
                yield factory(config, manager)
            except Exception as exc:  # pragma: no cover - configuration error
                log.warning("failed to instantiate strategy '%s': %s", key, exc)


class BucketTracker:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._usage: Dict[str, float] = defaultdict(float)
        self._exposure: float = 0.0
        self._initialized = False
        self._initialize_metrics()

    def snapshot(self) -> Dict[str, float]:
        return dict(self._usage)

    def headroom(self, bucket: str) -> float:
        budget = getattr(self.config.buckets, bucket, 0.0)
        used = self._usage.get(bucket, 0.0)
        return max(0.0, budget - used)

    def apply(self, bucket: str, fraction: float) -> None:
        self._usage[bucket] += fraction
        self._exposure += fraction
        self._set_metric(bucket)

    def decay(self, decay_factor: float = 0.95) -> None:
        for bucket in list(self._usage):
            self._usage[bucket] *= decay_factor
            self._set_metric(bucket)
        self._exposure *= decay_factor

    def release(self, bucket: str, fraction: float) -> None:
        if bucket not in self._usage:
            return
        self._usage[bucket] = max(0.0, self._usage[bucket] - fraction)
        self._exposure = max(0.0, self._exposure - fraction)
        self._set_metric(bucket)

    def _initialize_metrics(self) -> None:
        if self._initialized:
            return
        for bucket in ("futures_core", "spot_margin", "event", "reserve"):
            budget = getattr(self.config.buckets, bucket, None)
            if budget is None:
                continue
            try:
                strategy_bucket_usage_fraction.labels(bucket=bucket).set(
                    self._usage.get(bucket, 0.0)
                )
            except Exception:
                pass
        self._initialized = True

    def _set_metric(self, bucket: str) -> None:
        try:
            strategy_bucket_usage_fraction.labels(bucket=bucket).set(self._usage.get(bucket, 0.0))
        except Exception:
            pass


class RiskAllocator:
    def __init__(self, config: RuntimeConfig, portfolio: Portfolio) -> None:
        self.config = config
        self.portfolio = portfolio
        self.buckets = BucketTracker(config)
        self._open_positions: Dict[str, int] = defaultdict(int)
        self.daily_loss_realized: float = 0.0
        self._active_positions: Dict[str, Dict[str, float]] = defaultdict(dict)

    def _select_bucket(self, strategy: str) -> str:
        strat = strategy.lower()
        if strat in {"trend", "momentum"}:
            return "futures_core"
        if strat in {"scalper"}:
            return "futures_core"
        if strat in {"event", "listing", "meme"}:
            return "event"
        return "spot_margin"

    def _per_trade_risk(self, strategy: str) -> float:
        mapping = self.config.risk.per_trade_pct
        return float(mapping.get(strategy.lower(), mapping.get("default", 0.01)))

    def _bucket_budget(self, bucket: str) -> float:
        return getattr(self.config.buckets, bucket, 0.0)

    def _pick_leverage(self, symbol: str) -> Optional[int]:
        leverage_map = self.config.futures.leverage
        return (
            leverage_map.get(symbol.upper())
            or leverage_map.get("DEFAULT")
            or leverage_map.get("default")
        )

    def _desired_leverage(self, symbol: str) -> Optional[int]:
        overrides = getattr(self.config.futures, "desired_leverage", {}) or {}
        symbol_key = symbol.upper()
        if symbol_key in overrides:
            return overrides[symbol_key]
        return overrides.get("DEFAULT") or overrides.get("default")

    def _effective_leverage(self, symbol: str, desired: Optional[int]) -> int:
        if desired is not None and desired > 0:
            return max(1, int(desired))
        fallback = self._pick_leverage(symbol) or 1
        try:
            return max(1, int(fallback))
        except (TypeError, ValueError):
            return 1

    def _decide_venue(self, signal: Signal, bucket: str) -> str:
        if signal.venue_hint:
            return signal.venue_hint.lower()
        if bucket == "futures_core":
            return "futures"
        if bucket == "event":
            return "spot"
        return "spot"

    def _current_equity(self) -> float:
        state = getattr(self.portfolio, "state", None)
        if state is None:
            return 1.0
        equity = float(getattr(state, "equity", 0.0) or 0.0)
        cash = float(getattr(state, "cash", 0.0) or 0.0)
        return max(equity, cash, 1.0)

    def evaluate(self, signal: Signal) -> Optional[ExecutionOrder]:
        strategy_key = signal.normalized_strategy()
        bucket = self._select_bucket(strategy_key)
        symbol_key = signal.symbol.upper()
        existing_fraction = self._active_positions[strategy_key].get(symbol_key, 0.0)

        if self.buckets.headroom(bucket) <= 0:
            log.info("[risk] bucket '%s' exhausted; rejecting %s", bucket, signal)
            return None

        if (
            existing_fraction <= 0
            and self._open_positions[strategy_key] >= self.config.risk.max_concurrent
        ):
            log.info("[risk] %s at max concurrent positions; rejecting signal", strategy_key)
            return None

        per_trade_fraction = self._per_trade_risk(strategy_key)
        desired_leverage = self._desired_leverage(symbol_key)
        effective_leverage = self._effective_leverage(symbol_key, desired_leverage)

        desired_margin_fraction = per_trade_fraction / float(effective_leverage or 1)
        margin_headroom = self.buckets.headroom(bucket)
        margin_fraction = min(desired_margin_fraction, margin_headroom)
        if margin_fraction <= 0:
            log.info("[risk] margin headroom exhausted for %s; rejecting %s", bucket, signal)
            return None

        notional_fraction = min(per_trade_fraction, margin_fraction * effective_leverage)
        venue = self._decide_venue(signal, bucket)
        leverage = effective_leverage if venue == "futures" else None

        equity = self._current_equity()
        notional_usd = notional_fraction * equity
        if notional_usd < 5.0:
            log.debug(
                "[risk] notional %.2f below exchange minimum; dropping %s",
                notional_usd,
                signal,
            )
            return None

        self.buckets.apply(bucket, margin_fraction)
        if existing_fraction <= 0:
            self._open_positions[strategy_key] += 1
        self._active_positions[strategy_key][symbol_key] = existing_fraction + margin_fraction

        client_order_id = (
            f"{self.config.execution.client_id_prefix}:{signal.strategy}:{uuid.uuid4().hex[:10]}"
        )
        return ExecutionOrder(
            strategy=signal.strategy,
            symbol=signal.symbol,
            side=signal.side.upper(),
            venue=venue,
            notional_usd=notional_usd,
            notional_fraction=notional_fraction,
            bucket=bucket,
            leverage=leverage,
            configured_leverage=desired_leverage,
            effective_leverage=effective_leverage,
            margin_fraction=margin_fraction,
            reduce_only=False,
            stop=signal.stop,
            take_profit=signal.take_profit,
            client_order_id=client_order_id,
        )

    def cancel(self, order: ExecutionOrder) -> None:
        strategy_key = order.strategy.lower()
        symbol_key = order.symbol.upper()
        bucket = order.bucket
        current = self._active_positions[strategy_key].get(symbol_key, 0.0)
        remaining = current - order.margin_fraction
        if remaining <= 0:
            self._active_positions[strategy_key].pop(symbol_key, None)
            if self._open_positions[strategy_key] > 0:
                self._open_positions[strategy_key] -= 1
        else:
            self._active_positions[strategy_key][symbol_key] = max(0.0, remaining)
        if order.margin_fraction > 0:
            self.buckets.release(bucket, order.margin_fraction)

    def reconcile_position(self, order: ExecutionOrder) -> None:
        strategy_key = order.strategy.lower()
        symbol_key = order.symbol.upper()
        bucket = order.bucket
        if strategy_key not in self._active_positions:
            return
        if not self.portfolio:
            return
        positions = getattr(self.portfolio.state, "positions", {})
        pos = positions.get(symbol_key)
        qty = 0.0
        if pos is not None:
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
        if pos is not None and abs(qty) > 1e-8:
            return
        fraction = self._active_positions[strategy_key].pop(symbol_key, 0.0)
        if fraction > 0:
            self.buckets.release(bucket, fraction)
            if self._open_positions[strategy_key] > 0:
                self._open_positions[strategy_key] -= 1


class ExecutionRouter:
    """
    Thin wrapper on top of the existing order router. The scaffold logs intent
    and leaves concrete sizing/execution code to future iterations.
    """

    def __init__(self, router: order_router.OrderRouter, risk: RiskAllocator) -> None:
        self.router = router
        self.risk = risk
        try:
            self.portfolio = router.portfolio_service()
        except Exception:
            self.portfolio = None
        try:
            self._client = router.exchange_client()
        except Exception:
            self._client = None

    async def execute(self, order: ExecutionOrder) -> bool:
        usd_notional = max(float(order.notional_usd), 0.0)
        if usd_notional <= 0:
            log.debug("[exec] notional <= 0 for %s", order)
            self.risk.cancel(order)
            return False

        venue_hint = (order.venue or "spot").lower()
        symbol_base = order.symbol.split(".")[0].upper()
        qualified = order.symbol if "." in order.symbol else f"{symbol_base}.BINANCE"

        if venue_hint == "futures":
            leverage_ready = await self._ensure_leverage(symbol_base, order)
            if not leverage_ready:
                self.risk.cancel(order)
                return False

        if (
            venue_hint == "spot"
            and order.side.upper() == "SELL"
            and not self._has_spot_inventory(symbol_base)
        ):
            log.info("[exec] rejecting spot sell for %s; insufficient inventory", symbol_base)
            self.risk.cancel(order)
            return False

        log.info(
            "[exec] %s %s notional_usd=%.2f venue=%s leverage=%s stop=%s tp=%s id=%s",
            order.strategy,
            order.side,
            usd_notional,
            venue_hint,
            order.leverage,
            order.stop,
            order.take_profit,
            order.client_order_id,
        )

        try:
            result = await self.router.market_quote(
                symbol=qualified,
                side=order.side,
                quote=usd_notional,
                market=venue_hint,
            )
        except Exception as exc:
            log.warning("[exec] market order failed for %s: %s", qualified, exc, exc_info=True)
            self.risk.cancel(order)
            return False

        qty_filled = 0.0
        if isinstance(result, dict):
            qty_filled = float(
                result.get("filled_qty_base")
                or result.get("executedQty")
                or result.get("origQty")
                or 0.0
            )

        if qty_filled <= 0:
            self.risk.cancel(order)
            return False

        if venue_hint == "futures" and qty_filled > 0:
            hedge_side = "SELL" if order.side.upper() == "BUY" else "BUY"
            if order.stop:
                try:
                    await self.router.amend_stop_reduce_only(
                        qualified,
                        hedge_side,
                        float(order.stop),
                        abs(qty_filled),
                    )
                except Exception:
                    log.warning("[exec] stop placement failed for %s", qualified, exc_info=True)
            if order.take_profit:
                try:
                    await self.router.place_reduce_only_limit(
                        qualified,
                        hedge_side,
                        abs(qty_filled),
                        float(order.take_profit),
                    )
                except Exception:
                    log.warning(
                        "[exec] take-profit placement failed for %s",
                        qualified,
                        exc_info=True,
                    )
        self.risk.reconcile_position(order)
        return True

    def _has_spot_inventory(self, symbol: str) -> bool:
        if not self.portfolio:
            return True
        positions = getattr(self.portfolio.state, "positions", {})
        pos = positions.get(symbol.upper())
        if pos is None:
            return False
        quantity = float(getattr(pos, "quantity", 0.0) or 0.0)
        return quantity > 1e-8

    async def _ensure_leverage(self, symbol: str, order: ExecutionOrder) -> bool:
        client = getattr(self, "_client", None)
        if client is None or not hasattr(client, "futures_change_leverage"):
            return True
        configured = order.configured_leverage
        strategy_key = order.strategy.lower()
        symbol_key = symbol.upper()
        try:
            if configured is not None:
                t0 = time.perf_counter()
                resp = await client.futures_change_leverage(symbol=symbol, leverage=int(configured))
                applied = int(resp.get("leverage", configured))
                order.applied_leverage = applied
                order.leverage = applied
                leverage_set_latency_ms.observe((time.perf_counter() - t0) * 1000.0)
                strategy_leverage_configured.labels(strategy=strategy_key, symbol=symbol_key).set(
                    float(configured)
                )
                if applied != int(configured):
                    log.warning(
                        "[exec] leverage mismatch for %s: requested=%s applied=%s",
                        symbol,
                        configured,
                        applied,
                    )
                    strategy_leverage_mismatch_total.labels(
                        strategy=strategy_key, symbol=symbol_key
                    ).inc()
                    return False
                strategy_leverage_applied.labels(strategy=strategy_key, symbol=symbol_key).set(
                    float(applied)
                )
                return True

            position = await self._fetch_position(symbol)
            if position:
                try:
                    order.applied_leverage = int(float(position.get("leverage", 0) or 0))
                except Exception:
                    order.applied_leverage = None
            applied = order.applied_leverage or order.effective_leverage or 1
            order.leverage = applied
            strategy_leverage_configured.labels(strategy=strategy_key, symbol=symbol_key).set(
                float(order.effective_leverage or applied)
            )
            strategy_leverage_applied.labels(strategy=strategy_key, symbol=symbol_key).set(
                float(applied)
            )
            return True
        except Exception:
            log.warning("[exec] leverage preparation failed for %s", symbol, exc_info=True)
            strategy_leverage_mismatch_total.labels(strategy=strategy_key, symbol=symbol_key).inc()
            return False

    async def _fetch_position(self, symbol: str) -> Optional[dict[str, Any]]:
        client = getattr(self, "_client", None)
        if client is None or not hasattr(client, "position_risk"):
            return None
        try:
            positions = await client.position_risk(market="futures")
        except Exception:
            return None
        symbol_key = symbol.upper()
        for item in positions or []:
            if str(item.get("symbol", "")).upper() == symbol_key:
                return item
        return None


class StrategyPipeline:
    def __init__(
        self,
        config: RuntimeConfig,
        registry: StrategyRegistry,
        order_router: order_router.OrderRouter,
        manager: UniverseManager,
        queue: Optional[asyncio.Queue[tuple[Signal, float]]] = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.queue = queue or asyncio.Queue(maxsize=config.bus.max_queue)
        self.router = order_router
        self.manager = manager
        self.risk = RiskAllocator(config, order_router.portfolio_service())
        self.executor = ExecutionRouter(order_router, self.risk)
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def _consumer(self) -> None:
        log.info("[runtime] consumer loop online")
        while self._running:
            signal, published_at = await self.queue.get()
            latency = max(0.0, time.time() - published_at)
            strategy_signals_total.labels(strategy=signal.strategy.lower()).inc()
            strategy_signal_latency_seconds.labels(strategy=signal.strategy.lower()).observe(
                latency
            )
            try:
                strategy_signal_queue_len.labels(strategy=signal.strategy.lower()).set(
                    self.queue.qsize()
                )
                strategy_signal_queue_latency_sec.labels(strategy=signal.strategy.lower()).set(
                    latency
                )
            except Exception:
                pass

            if signal.ttl and latency > signal.ttl:
                log.debug(
                    "[runtime] dropping stale signal %s (latency=%.2fs)",
                    signal,
                    latency,
                )
                continue

            resolved = resolve_market(f"{signal.symbol}.BINANCE", signal.venue_hint or "")
            if resolved:
                signal.meta["resolved_market"] = resolved

            order = self.risk.evaluate(signal)
            if not order:
                continue
            try:
                success = await self.executor.execute(order)
                if success:
                    strategy_orders_total.labels(
                        symbol=signal.symbol,
                        venue=order.venue.upper(),
                        side=signal.side.upper(),
                        source=signal.strategy,
                    ).inc()
            except Exception:
                self.risk.cancel(order)
                log.warning(
                    "[runtime] execution failed for %s %s",
                    signal.strategy,
                    signal.symbol,
                    exc_info=True,
                )

    async def run(self) -> None:
        if self._running:
            return
        self._running = True
        producers = list(self.registry.build_all(self.config, self.manager))

        for producer in producers:
            task = asyncio.create_task(
                producer.run(self.queue, self.config), name=f"producer:{producer.name}"
            )
            self._tasks.append(task)
        self._tasks.append(asyncio.create_task(self._consumer(), name="signal-consumer"))
        await asyncio.gather(*self._tasks)

    def cancel(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
