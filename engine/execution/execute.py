from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Sequence

from engine import metrics
from engine.idempotency import CACHE, append_jsonl
from engine.risk import RiskRails


def _bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    try:
        return bool(int(value))
    except Exception:  # noqa: BLE001 - defensive
        return bool(value)


def _idempotency_key(signal: Dict[str, Any], hint: Optional[str] = None) -> str:
    if hint:
        return hint
    strategy = str(signal.get("strategy") or "strategy").lower()
    symbol = str(signal.get("symbol") or "?").upper()
    side = str(signal.get("side") or "?").upper()
    ts = signal.get("ts")
    try:
        ts_part = int(ts)
    except Exception:  # noqa: BLE001 - fallback to now
        ts_part = int(time.time())
    return f"sig:{strategy}:{symbol}:{side}:{ts_part}"


def _is_async_callable(fn: Any) -> bool:
    if inspect.iscoroutinefunction(fn):
        return True
    call = getattr(fn, "__call__", None)
    if call and inspect.iscoroutinefunction(call):
        return True
    func = getattr(fn, "__func__", None)
    if func and inspect.iscoroutinefunction(func):
        return True
    return False


@dataclass(frozen=True)
class RecordedOrder:
    """Captured order metadata when running in dry run or backtest mode."""

    timestamp: float
    symbol: str
    side: str
    tag: str
    status: str
    quote: Optional[float]
    quantity: Optional[float]
    market: Optional[str]
    meta: Any
    idempotency_key: str
    size: Optional[float]
    size_type: Optional[str]
    signal: Dict[str, Any]


class StrategyExecutor:
    """Unified execution path for strategy signals."""

    def __init__(
        self,
        *,
        risk: RiskRails,
        router: Any,
        default_dry_run: bool,
        config_hash_getter: Optional[Callable[[], str]] = None,
        source: str = "strategy",
        backtest_mode: bool = False,
        order_recorder: Optional[Callable[[RecordedOrder], None]] = None,
    ) -> None:
        self._risk = risk
        self._router = router
        self._default_dry_run = bool(default_dry_run)
        self._config_hash_getter = config_hash_getter
        self._source = source
        self._backtest_mode = bool(backtest_mode)
        self._order_recorder = order_recorder
        self._recorded_orders: List[RecordedOrder] = []

    @property
    def recorded_orders(self) -> Sequence[RecordedOrder]:
        return tuple(self._recorded_orders)

    async def execute(
        self,
        signal: Dict[str, Any],
        *,
        idem_key: Optional[str] = None,
        dry_run_override: Optional[bool] = None,
    ) -> Dict[str, Any]:
        key = _idempotency_key(signal, idem_key)
        cached = CACHE.get(key)
        if cached:
            return cached

        symbol = str(signal.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("signal requires symbol")
        side = str(signal.get("side") or "").upper() or "BUY"
        market = signal.get("market")
        if isinstance(market, str):
            market_hint = market.lower()
        else:
            market_hint = None

        quote = signal.get("quote")
        quantity = signal.get("quantity")

        eff_dry = _bool(signal.get("dry_run"))
        if eff_dry is None:
            eff_dry = _bool(dry_run_override)
        if eff_dry is None:
            eff_dry = self._default_dry_run

        ok, err = self._risk.check_order(
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            quote=None if quote is None else float(quote),
            quantity=None if quantity is None else float(quantity),
            market=market_hint,
        )
        if not ok:
            metrics.orders_rejected.inc()
            payload = {
                "status": "rejected",
                **err,
                "source": self._source,
                "idempotency_key": key,
            }
            CACHE.set(key, payload)
            return payload

        tag = str(signal.get("tag") or signal.get("strategy") or self._source)
        meta = signal.get("meta")
        ts = time.time()

        order_ctx = {
            "symbol": symbol,
            "side": side,
            "quote": None if quote is None else float(quote),
            "quantity": None if quantity is None else float(quantity),
            "market": market_hint,
            "tag": tag,
            "meta": meta,
            "idempotency_key": key,
        }

        should_record_only = bool(eff_dry or self._backtest_mode)

        if should_record_only:
            if eff_dry and not self._backtest_mode:
                status = "dry_run"
            else:
                status = "backtest"
            payload = {
                "status": status,
                "symbol": order_ctx["symbol"],
                "side": order_ctx["side"],
                "quote": order_ctx["quote"],
                "quantity": order_ctx["quantity"],
                "market": order_ctx["market"],
                "order": order_ctx,
                "signal": signal,
                "timestamp": ts,
                "idempotency_key": key,
            }
            cfg_hash = self._safe_config_hash()
            if cfg_hash:
                payload["cfg_hash"] = cfg_hash
            append_jsonl("orders.jsonl", payload)
            self._record_order(
                timestamp=ts,
                status=status,
                order_ctx=order_ctx,
                signal=signal,
                idem_key=key,
            )
            CACHE.set(key, payload)
            return payload

        result = await self._submit(symbol, side, quote, quantity, market_hint, tag, meta)

        metrics.orders_submitted.inc()
        payload = {
            "status": "submitted",
            "order": {**order_ctx, "result": result},
            "signal": signal,
            "timestamp": ts,
        }
        cfg_hash = self._safe_config_hash()
        if cfg_hash:
            payload["cfg_hash"] = cfg_hash
        append_jsonl("orders.jsonl", payload)
        CACHE.set(key, payload)
        return payload

    def _record_order(
        self,
        *,
        timestamp: float,
        status: str,
        order_ctx: Dict[str, Any],
        signal: Dict[str, Any],
        idem_key: str,
    ) -> None:
        size: Optional[float]
        size_type: Optional[str]
        quantity = order_ctx.get("quantity")
        quote = order_ctx.get("quote")
        if quantity is not None:
            try:
                size = float(quantity)
            except Exception:  # noqa: BLE001 - defensive conversion
                size = None
            size_type = "quantity"
        elif quote is not None:
            try:
                size = float(quote)
            except Exception:  # noqa: BLE001 - defensive conversion
                size = None
            size_type = "quote"
        else:
            size = None
            size_type = None

        recorded = RecordedOrder(
            timestamp=float(timestamp),
            symbol=str(order_ctx.get("symbol") or ""),
            side=str(order_ctx.get("side") or ""),
            tag=str(order_ctx.get("tag") or self._source),
            status=status,
            quote=None if quote is None else float(quote),
            quantity=None if quantity is None else float(quantity),
            market=order_ctx.get("market"),
            meta=order_ctx.get("meta"),
            idempotency_key=idem_key,
            size=size,
            size_type=size_type,
            signal=dict(signal),
        )
        self._recorded_orders.append(recorded)
        if self._order_recorder:
            try:
                self._order_recorder(recorded)
            except Exception:  # noqa: BLE001 - recorder must not break execution
                pass

    def execute_sync(
        self,
        signal: Dict[str, Any],
        *,
        idem_key: Optional[str] = None,
        dry_run_override: Optional[bool] = None,
    ) -> Dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(
                self.execute(signal, idem_key=idem_key, dry_run_override=dry_run_override),
                loop,
            )
            return fut.result()
        return asyncio.run(
            self.execute(signal, idem_key=idem_key, dry_run_override=dry_run_override)
        )

    async def _submit(
        self,
        symbol: str,
        side: str,
        quote: Any,
        quantity: Any,
        market_hint: Optional[str],
        tag: str,
        meta: Any,
    ) -> Any:
        submit_callable = None
        call_kwargs: Dict[str, Any] = {}
        fallback_args: Optional[tuple[Any, ...]] = None

        if quote is not None:
            submit_callable = getattr(self._router, "market_quote", None)
            if submit_callable:
                call_kwargs = {"symbol": symbol, "side": side, "quote": float(quote)}
                if market_hint is not None:
                    call_kwargs["market"] = market_hint
                args: tuple[Any, ...] = (symbol, side, float(quote))
                if market_hint is not None:
                    args = (*args, market_hint)
                fallback_args = args
        if submit_callable is None:
            submit_callable = getattr(self._router, "place_market_order", None)
            if submit_callable:
                call_kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "quote": None if quote is None else float(quote),
                    "quantity": None if quantity is None else float(quantity),
                }
                if market_hint is not None:
                    call_kwargs["market"] = market_hint
                base_args = (
                    symbol,
                    side,
                    None if quote is None else float(quote),
                    None if quantity is None else float(quantity),
                )
                fallback_args = (*base_args, market_hint) if market_hint is not None else base_args
        if submit_callable is None:
            submit_callable = getattr(self._router, "place_market_order_async", None)
            if submit_callable:
                call_kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "quote": None if quote is None else float(quote),
                    "quantity": None if quantity is None else float(quantity),
                }
                if market_hint is not None:
                    call_kwargs["market"] = market_hint
                base_args = (
                    symbol,
                    side,
                    None if quote is None else float(quote),
                    None if quantity is None else float(quantity),
                )
                fallback_args = (*base_args, market_hint) if market_hint is not None else base_args
        if submit_callable is None:
            raise RuntimeError("router does not expose market order submission")

        loop = asyncio.get_running_loop()
        context = {
            "meta": meta,
            "tag": tag,
            "symbol": symbol,
            "side": side,
            "market": market_hint,
        }
        cleanup = False
        try:
            setattr(self._router, "_strategy_pending_meta", context)
            cleanup = True
        except Exception:  # noqa: BLE001
            cleanup = False

        is_async_callable = _is_async_callable(submit_callable)

        async def _invoke_with_kwargs() -> Any:
            if is_async_callable:
                return await submit_callable(**call_kwargs)
            return await loop.run_in_executor(None, partial(submit_callable, **call_kwargs))

        try:
            try:
                result = await _invoke_with_kwargs()
            except TypeError as exc:
                handled = False
                if "unexpected keyword" in str(exc):
                    alt_kwargs = None
                    if "quote" in call_kwargs and "notional" not in call_kwargs:
                        alt_kwargs = dict(call_kwargs)
                        alt_kwargs["notional"] = alt_kwargs.pop("quote")
                    if alt_kwargs is not None:
                        if is_async_callable:
                            result = await submit_callable(**alt_kwargs)
                        else:
                            result = await loop.run_in_executor(
                                None, partial(submit_callable, **alt_kwargs)
                            )
                        handled = True
                    elif fallback_args:
                        if is_async_callable:
                            result = await submit_callable(*fallback_args)
                        else:
                            result = await loop.run_in_executor(
                                None, lambda: submit_callable(*fallback_args)
                            )
                        handled = True
                if not handled:
                    raise
        finally:
            if cleanup:
                try:
                    if getattr(self._router, "_strategy_pending_meta", None) is context:
                        delattr(self._router, "_strategy_pending_meta")
                except Exception:  # noqa: BLE001 - defensive cleanup
                    pass
        return result

    def _safe_config_hash(self) -> Optional[str]:
        if not self._config_hash_getter:
            return None
        try:
            return str(self._config_hash_getter())
        except Exception:  # noqa: BLE001
            return None


__all__ = ["StrategyExecutor", "RecordedOrder"]
