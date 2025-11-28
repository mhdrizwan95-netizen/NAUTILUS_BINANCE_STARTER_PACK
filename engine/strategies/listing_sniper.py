from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import httpx

from engine.core.event_bus import BUS
from engine.core.market_resolver import resolve_market_choice
from engine.core.order_router import OrderRouter
from engine.core.signal_queue import SIGNAL_QUEUE, QueuedEvent
from engine.execution.execute import StrategyExecutor
from engine.metrics import (
    listing_sniper_announcements_total,
    listing_sniper_cooldown_epoch,
    listing_sniper_go_live_epoch,
    listing_sniper_last_announce_epoch,
    listing_sniper_orders_total,
    listing_sniper_skips_total,
)
from engine.risk import RiskRails
from shared.cooldown import CooldownTracker
from shared.listing_utils import generate_listing_targets

logger = logging.getLogger("engine.strategies.listing_sniper")
_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    asyncio.TimeoutError,
)


def _env_bool(name: str, default: bool) -> bool:
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_float_list(name: str, default: Sequence[float]) -> tuple[float, ...]:
    import os

    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    values: list[float] = []
    for part in raw.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        if token.endswith("%"):
            token = token[:-1].strip()
            try:
                values.append(float(token) / 100.0)
            except ValueError:
                continue
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    return tuple(values or default)


@dataclass(frozen=True)
class ListingSniperConfig:
    enabled: bool = False
    dry_run: bool = True
    per_trade_risk_pct: float = 0.0075  # risk ~0.75% of equity
    stop_loss_pct: float = 0.12
    fallback_equity_usd: float = 2_000.0
    min_notional_usd: float = 25.0
    max_notional_usd: float = 250.0
    entry_delay_sec: float = 12.0
    entry_timeout_sec: float = 180.0
    price_poll_sec: float = 2.0
    max_chase_pct: float = 0.45
    max_spread_pct: float = 0.05
    cooldown_sec: float = 900.0
    max_parallel_tasks: int = 3
    take_profit_levels: tuple[float, ...] = (0.5, 1.0)
    forward_legacy_event: bool = True
    metrics_enabled: bool = True
    dex_bridge_enabled: bool = False
    default_market: str = "spot"


def load_listing_sniper_config() -> ListingSniperConfig:
    import os

    default_market_raw = os.getenv("LISTING_SNIPER_DEFAULT_MARKET", "").strip().lower()
    default_market = default_market_raw or "spot"
    if default_market not in {"spot", "margin", "futures", "options"}:
        default_market = "spot"
    return ListingSniperConfig(
        enabled=_env_bool("LISTING_SNIPER_ENABLED", False),
        dry_run=_env_bool("LISTING_SNIPER_DRY_RUN", True),
        per_trade_risk_pct=_env_float("LISTING_SNIPER_RISK_PCT", 0.0075),
        stop_loss_pct=_env_float("LISTING_SNIPER_STOP_PCT", 0.12),
        fallback_equity_usd=_env_float("LISTING_SNIPER_FALLBACK_EQUITY", 2_000.0),
        min_notional_usd=_env_float("LISTING_SNIPER_MIN_NOTIONAL_USD", 25.0),
        max_notional_usd=_env_float("LISTING_SNIPER_MAX_NOTIONAL_USD", 250.0),
        entry_delay_sec=_env_float("LISTING_SNIPER_ENTRY_DELAY_SEC", 12.0),
        entry_timeout_sec=_env_float("LISTING_SNIPER_ENTRY_TIMEOUT_SEC", 180.0),
        price_poll_sec=_env_float("LISTING_SNIPER_PRICE_POLL_SEC", 2.0),
        max_chase_pct=_env_float("LISTING_SNIPER_MAX_CHASE_PCT", 0.45),
        max_spread_pct=_env_float("LISTING_SNIPER_MAX_SPREAD_PCT", 0.05),
        cooldown_sec=_env_float("LISTING_SNIPER_COOLDOWN_SEC", 900.0),
        max_parallel_tasks=_env_int("LISTING_SNIPER_MAX_PARALLEL", 3),
        take_profit_levels=_env_float_list("LISTING_SNIPER_TP_LEVELS", (0.5, 1.0)),
        forward_legacy_event=_env_bool("LISTING_SNIPER_FORWARD_LEGACY", True),
        metrics_enabled=_env_bool("LISTING_SNIPER_METRICS_ENABLED", True),
        dex_bridge_enabled=_env_bool("LISTING_SNIPER_DEX_BRIDGE_ENABLED", False),
        default_market=default_market,
    )


@dataclass
class ListingOpportunity:
    symbol: str
    article_id: str
    title: str
    url: str | None
    announced_at: float
    go_live_at: float | None
    initial_price: float | None = None
    attempts: int = 0


class ListingSniper:
    """
    Event-driven listing sniper that reacts to Binance listing announcements.
    """

    def __init__(
        self,
        router: OrderRouter,
        risk: RiskRails,
        rest_client: Any,
        cfg: ListingSniperConfig | None = None,
    ) -> None:
        self.cfg = cfg or load_listing_sniper_config()
        self.router = router
        self.risk = risk
        self.rest_client = rest_client
        self._cooldowns = CooldownTracker(self.cfg.cooldown_sec)
        self._tasks: set[asyncio.Task] = set()
        self._seen_ids: set[str] = set()
        self._forwarded: set[str] = set()
        self._opportunities: dict[str, ListingOpportunity] = {}
        self._dex_forwarded: set[str] = set()
        self._executor = StrategyExecutor(
            risk=risk,
            router=router,
            default_dry_run=self.cfg.dry_run,
            source="listing_sniper",
        )

    # ------------------------------------------------------------------ public API
    async def on_external_event(self, evt: dict[str, Any]) -> None:
        if not self.cfg.enabled:
            return
        source = str(evt.get("source") or "").lower()
        if source not in {"binance_listings", "listing_sniper_bridge"}:
            return

        payload = evt.get("payload") or {}
        article_id = str(payload.get("id") or payload.get("articleId") or "").strip()
        title = str(payload.get("title") or payload.get("titleText") or "").strip()
        url = payload.get("url") or payload.get("linkUrl")
        announced_at = self._parse_timestamp(payload.get("published") or payload.get("publishTime"))
        go_live_at = self._extract_go_live_at(payload, title)
        tickers = self._extract_symbols(evt)
        if not tickers:
            return

        for raw_symbol in tickers:
            symbol = raw_symbol.upper()
            if not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"
            key = f"{article_id}:{symbol}" if article_id else f"{symbol}:{int(announced_at)}"
            if key in self._seen_ids:
                continue

            self._seen_ids.add(key)
            self._record_announcement(symbol, announced_at, go_live_at)
            opportunity = ListingOpportunity(
                symbol=symbol,
                article_id=article_id or key,
                title=title,
                url=str(url) if url else None,
                announced_at=announced_at,
                go_live_at=go_live_at,
            )
            self._opportunities[symbol] = opportunity
            if self.cfg.forward_legacy_event:
                await self._forward_legacy(symbol, announced_at)

            if self.cfg.max_parallel_tasks > 0 and len(self._tasks) >= self.cfg.max_parallel_tasks:
                self._record_skip(symbol, "too_many_active")
                continue

            task = asyncio.create_task(self._enter_post_listing(opportunity))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------------ internals
    def _record_announcement(
        self, symbol: str, announced_at: float, go_live_at: float | None
    ) -> None:
        if self.cfg.metrics_enabled:
            listing_sniper_announcements_total.labels(symbol=symbol, action="received").inc()
            listing_sniper_last_announce_epoch.labels(symbol=symbol).set(float(announced_at))
            if go_live_at:
                listing_sniper_go_live_epoch.labels(symbol=symbol).set(float(go_live_at))

    def _record_skip(self, symbol: str, reason: str) -> None:
        if self.cfg.metrics_enabled:
            listing_sniper_skips_total.labels(symbol=symbol, reason=reason).inc()

    def _set_cooldown(self, symbol: str) -> None:
        until = self._cooldowns.set(symbol)
        if self.cfg.metrics_enabled and until and listing_sniper_cooldown_epoch is not None:
            listing_sniper_cooldown_epoch.labels(symbol=symbol).set(until)

    def _cooldown_active(self, symbol: str) -> bool:
        if self._cooldowns.active(symbol):
            self._record_skip(symbol, "cooldown")
            return True
        return False

    async def _enter_post_listing(self, op: ListingOpportunity) -> None:
        symbol = op.symbol
        if self._cooldown_active(symbol):
            return

        await self._await_go_live(op)

        start = time.time()
        baseline: float | None = None
        last_price: float = 0.0
        last_spread: float = 0.0

        while time.time() - start <= self.cfg.entry_timeout_sec:
            price, spread = await self._price_with_spread(symbol)
            if price > 0:
                last_price = price
                last_spread = spread
                if baseline is None:
                    baseline = price
                move = 0.0 if baseline is None else (price - baseline) / max(baseline, 1e-9)
                if move > self.cfg.max_chase_pct:
                    logger.info("[LISTING] %s skipped due to chase %.2f%%", symbol, move * 100)
                    self._record_skip(symbol, "chase")
                    self._set_cooldown(symbol)
                    return
                if spread > self.cfg.max_spread_pct:
                    await asyncio.sleep(self.cfg.price_poll_sec)
                    continue
                break
            await asyncio.sleep(self.cfg.price_poll_sec)

        if last_price <= 0:
            logger.info("[LISTING] %s skipped (no price within window)", symbol)
            self._record_skip(symbol, "price_timeout")
            self._set_cooldown(symbol)
            return

        op.initial_price = op.initial_price or baseline or last_price

        notional = self._sizing_notional()
        if notional <= 0:
            self._record_skip(symbol, "sizing")
            self._set_cooldown(symbol)
            return

        full_symbol = f"{symbol}.BINANCE"
        market_choice = resolve_market_choice(full_symbol, self.cfg.default_market)

        try:
            execution = await self._executor.execute(
                {
                    "strategy": "listing_sniper",
                    "symbol": full_symbol,
                    "side": "BUY",
                    "quote": notional,
                    "market": market_choice,
                    "meta": {
                        "article_id": op.article_id,
                        "announced_at": op.announced_at,
                        "go_live_at": op.go_live_at,
                        "initial_price": op.initial_price,
                    },
                    "tag": "listing_entry",
                    "ts": time.time(),
                }
            )
        except _SUPPRESSIBLE_EXCEPTIONS as exc:  # noqa: BLE001
            logger.warning("[LISTING] execution failed for %s: %s", symbol, exc)
            self._record_skip(symbol, "execution_exception")
            if self.cfg.metrics_enabled:
                listing_sniper_orders_total.labels(symbol=symbol, status="failed").inc()
            self._set_cooldown(symbol)
            return

        status = str(execution.get("status") or "unknown")
        if status == "rejected":
            reason = str(execution.get("error") or execution.get("reason") or "risk")
            self._record_skip(symbol, reason)
            if self.cfg.metrics_enabled:
                listing_sniper_orders_total.labels(symbol=symbol, status="rejected").inc()
            self._set_cooldown(symbol)
            return

        if self.cfg.metrics_enabled:
            listing_sniper_orders_total.labels(symbol=symbol, status=status).inc()

        if status == "dry_run":
            logger.info(
                "[LISTING] dry-run %s BUY %.2f USD baseline=%.4f spread=%.4f market=%s",
                symbol,
                notional,
                last_price,
                last_spread,
                market_choice,
            )
            self._set_cooldown(symbol)
            return

        order_payload = execution.get("order", {})
        router_result = order_payload.get("result", {})
        try:
            avg_fill = float(router_result.get("avg_fill_price") or last_price)
            qty_filled = float(
                router_result.get("filled_qty_base") or router_result.get("executedQty") or 0.0
            )
        except _SUPPRESSIBLE_EXCEPTIONS:
            avg_fill = last_price
            qty_filled = 0.0

        logger.info(
            "[LISTING] executed %s BUY %.2f USD -> avg=%.4f qty=%.6f market=%s",
            symbol,
            notional,
            avg_fill,
            qty_filled,
            market_choice,
        )
        await self._deploy_exit_plan(full_symbol, router_result, last_price, market_choice)
        self._set_cooldown(symbol)

    def _sizing_notional(self) -> float:
        try:
            equity = float(self.router._portfolio.state.equity)  # type: ignore[attr-defined]
        except _SUPPRESSIBLE_EXCEPTIONS:
            equity = 0.0
        if equity <= 0:
            equity = float(self.cfg.fallback_equity_usd)
        risk_budget = max(0.0, equity * float(self.cfg.per_trade_risk_pct))
        if self.cfg.stop_loss_pct > 0:
            notional = risk_budget / max(self.cfg.stop_loss_pct, 1e-9)
        else:
            notional = risk_budget
        notional = max(
            float(self.cfg.min_notional_usd),
            min(float(self.cfg.max_notional_usd), notional),
        )
        return notional

    async def _await_go_live(self, op: ListingOpportunity) -> None:
        now = time.time()
        wait_until = max(op.announced_at, now)
        if op.go_live_at is not None:
            go_live_at = float(op.go_live_at)
            if go_live_at < now and (now - go_live_at) < 1.0:
                go_live_at = go_live_at + 1.0
            wait_until = max(wait_until, go_live_at)
        wait_until += max(self.cfg.entry_delay_sec, 0.0)
        while True:
            remaining = wait_until - time.time()
            if remaining <= 0:
                break
            logger.info("[LISTING] %s waiting %.2fs for go-live window", op.symbol, remaining)
            await asyncio.sleep(min(remaining, 0.05))

    async def _deploy_exit_plan(
        self,
        symbol: str,
        execution: dict[str, Any],
        fallback_price: float,
        _market_choice: str | None,
    ) -> None:
        qty = float(execution.get("filled_qty_base") or execution.get("executedQty") or 0.0)
        avg_px = float(
            execution.get("avg_fill_price") or execution.get("avgPrice") or fallback_price or 0.0
        )
        if qty <= 0 or avg_px <= 0:
            return

        stop_price, target_prices = generate_listing_targets(
            avg_px,
            stop_pct=float(self.cfg.stop_loss_pct),
            target_multipliers=(lvl for lvl in self.cfg.take_profit_levels if lvl > 0),
        )

        if stop_price is not None:
            stop_price = max(avg_px * 0.0001, stop_price)
            try:
                await self.router.amend_stop_reduce_only(symbol, "SELL", stop_price, abs(qty))
            except _SUPPRESSIBLE_EXCEPTIONS as exc:  # noqa: BLE001
                logger.debug("[LISTING] stop placement failed for %s: %s", symbol, exc)

        levels = [price for price in target_prices if price > 0]
        if not levels:
            return

        per_clip = qty / float(len(levels))
        placed = 0.0
        rounder = getattr(self.router, "round_tick", None)
        for idx, raw_price in enumerate(levels):
            price = raw_price
            if callable(rounder):
                try:
                    price = rounder(symbol, raw_price)
                except _SUPPRESSIBLE_EXCEPTIONS:
                    price = raw_price
            clip_qty = per_clip if idx < len(levels) - 1 else max(qty - placed, 0.0)
            placed += clip_qty
            if clip_qty <= 0:
                continue
            try:
                await self.router.place_reduce_only_limit(symbol, "SELL", clip_qty, price)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:  # noqa: BLE001
                logger.debug("[LISTING] tp placement failed for %s @%.4f: %s", symbol, price, exc)

    async def _forward_legacy(self, symbol: str, announced_at: float) -> None:
        key = f"{symbol}:{int(announced_at)}"
        if key in self._forwarded:
            return
        self._forwarded.add(key)
        try:
            payload = {
                "source": "listing_sniper_bridge",
                "payload": {
                    "symbol": symbol,
                    "announced_at": int(announced_at * 1000.0),
                    "time": int(announced_at * 1000.0),
                    "forwarded_by": "listing_sniper",
                },
                "asset_hints": [symbol],
                "priority": 0.8,
                "meta": {"bridge": "listing_sniper_bridge"},
            }
            await SIGNAL_QUEUE.put(
                QueuedEvent(
                    topic="events.external_feed",
                    data=payload,
                    priority=float(payload.get("priority", 0.8)),
                    source="listing_sniper_bridge",
                )
            )
        except _SUPPRESSIBLE_EXCEPTIONS:
            logger.debug("[LISTING] failed to forward legacy event for %s", symbol)
        await self._maybe_emit_dex_candidate(symbol)

    async def _maybe_emit_dex_candidate(self, symbol: str) -> None:
        if not self.cfg.dex_bridge_enabled:
            return
        base = symbol.upper().replace("USDT", "").replace("BUSD", "")
        if base in self._dex_forwarded:
            return
        candidate = await self._fetch_dex_candidate(base)
        if not candidate:
            return
        if not candidate["token_address"] or not candidate["pair_address"]:
            return
        payload = {
            "symbol": candidate["symbol"],
            "chain": candidate["chain"],
            "addr": candidate["token_address"],
            "pair": candidate["pair_address"],
            "tier": candidate["tier"],
            "price": candidate["price_usd"],
            "liq": candidate["liquidity_usd"],
            "mcap": candidate["mcap_usd"],
            "vol1h": candidate["vol_1h"],
            "vol24h": candidate["vol_24h"],
            "chg5m": candidate["change_5m"],
            "holders": candidate.get("holders"),
            "meta": {
                "source": "listing_sniper_bridge",
                "listing_symbol": symbol,
                "volume_ratio": candidate.get("volume_ratio"),
            },
        }
        try:
            await BUS.publish("strategy.dex_candidate", payload)
            self._dex_forwarded.add(base)
        except _SUPPRESSIBLE_EXCEPTIONS:
            logger.debug("[LISTING] dex candidate publish failed for %s", symbol)

    async def _fetch_dex_candidate(self, token: str) -> dict[str, Any] | None:
        url = f"https://api.dexscreener.com/latest/dex/search?q={token}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json() or {}
        except _SUPPRESSIBLE_EXCEPTIONS:
            return None
        pairs = data.get("pairs") or data.get("tokens") or []
        token_upper = token.upper()
        best: dict[str, Any] | None = None
        best_liq = 0.0
        for item in pairs:
            base_meta = item.get("baseToken") or {}
            sym = str(base_meta.get("symbol") or item.get("symbol") or "").upper()
            if token_upper not in {sym, sym.replace("USDT", "")}:
                continue
            liq = self._as_float((item.get("liquidity") or {}).get("usd"))
            if liq < 200_000:
                continue
            if liq <= best_liq:
                continue
            best = item
            best_liq = liq
        if not best:
            return None
        volume = best.get("volume") or {}
        vol24 = self._as_float(volume.get("h24"))
        vol1h = self._as_float(volume.get("h1"))
        avg1h = (vol24 / 24.0) if vol24 > 0 else 0.0
        volume_ratio = (vol1h / avg1h) if avg1h > 0 else 0.0
        tier = "A" if volume_ratio >= 5.0 else "B"
        change_ref = best.get("priceChange") or {}
        return {
            "symbol": token_upper,
            "chain": str(best.get("chainId") or best.get("chain") or "").upper(),
            "token_address": (best.get("baseToken") or {}).get("address")
            or best.get("baseTokenAddress")
            or "",
            "pair_address": best.get("pairAddress") or best.get("id") or "",
            "price_usd": self._as_float(best.get("priceUsd") or best.get("price")),
            "liquidity_usd": best_liq,
            "mcap_usd": self._as_float(best.get("fdv") or best.get("mcap")),
            "vol_1h": vol1h,
            "vol_24h": vol24,
            "change_5m": self._as_float(change_ref.get("m5") or best.get("change5m")),
            "holders": best.get("holders"),
            "tier": tier,
            "volume_ratio": volume_ratio,
        }

    async def _price_with_spread(self, symbol: str) -> tuple[float, float]:
        client = self.rest_client
        if client is None:
            return 0.0, 0.0

        price = 0.0
        spread = 0.0
        try:
            book_fn = getattr(client, "book_ticker", None)
            if callable(book_fn):
                res = book_fn(symbol)
                if inspect.isawaitable(res):
                    res = await res
                bid = self._as_float(res.get("bidPrice") if isinstance(res, dict) else None)
                ask = self._as_float(res.get("askPrice") if isinstance(res, dict) else None)
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2.0
                    spread = abs(ask - bid) / max(price, 1e-9)
            if price <= 0:
                px_fn = getattr(client, "ticker_price", None)
                if callable(px_fn):
                    res = px_fn(symbol)
                    if inspect.isawaitable(res):
                        res = await res
                    price = self._extract_price(res)
        except _SUPPRESSIBLE_EXCEPTIONS as exc:  # noqa: BLE001
            logger.debug("[LISTING] price fetch failed for %s: %s", symbol, exc)
        return price, spread

    def _extract_symbols(self, evt: dict[str, Any]) -> set[str]:
        symbols: set[str] = set()
        for hint in evt.get("asset_hints") or []:
            sym = str(hint).upper().strip()
            if not sym:
                continue
            if "." in sym:
                sym = sym.split(".")[0]
            symbols.add(sym)
        payload = evt.get("payload") or {}
        for ticker in payload.get("tickers") or []:
            sym = str(ticker).upper().strip()
            if not sym:
                continue
            symbols.add(sym)
        return symbols

    def _extract_go_live_at(self, payload: dict[str, Any], title: str) -> float | None:
        for key in (
            "goLiveTime",
            "go_live_time",
            "tradingOpenTime",
            "trading_open_time",
        ):
            if payload.get(key) is not None:
                return self._parse_timestamp(payload[key])

        extra = []
        for field in ("content", "summary", "body", "articleContent", "richText"):
            value = payload.get(field)
            if isinstance(value, str):
                extra.append(value)
        if isinstance(title, str):
            extra.append(title)
        for text in extra:
            ts = self._parse_go_live_from_text(text)
            if ts:
                return ts
        return None

    def _parse_go_live_from_text(self, text: str) -> float | None:
        if not text:
            return None
        import re
        from datetime import datetime

        for line in text.splitlines():
            lowered = line.lower()
            if "trading" not in lowered:
                continue
            match = re.search(
                r"(\d{4})[\-/](\d{1,2})[\-/](\d{1,2}).{0,20}?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?",
                line,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            year, month, day, hour, minute, second, ampm = match.groups()
            try:
                hour_i = int(hour)
                minute_i = int(minute)
                second_i = int(second or 0)
                if ampm:
                    ampm_lower = ampm.lower()
                    if ampm_lower == "pm" and hour_i < 12:
                        hour_i += 12
                    if ampm_lower == "am" and hour_i == 12:
                        hour_i = 0
                dt = datetime(
                    int(year),
                    int(month),
                    int(day),
                    hour_i,
                    minute_i,
                    second_i,
                    tzinfo=UTC,
                )
                return dt.timestamp()
            except _SUPPRESSIBLE_EXCEPTIONS:
                continue
        return None

    @staticmethod
    def _parse_timestamp(value: Any) -> float:
        if value is None:
            return time.time()
        if isinstance(value, (int, float)):
            val = float(value)
            if val > 10_000_000_000:  # treat as ms
                return val / 1000.0
            return val
        try:
            text = str(value).strip()
            if text.isdigit():
                val = float(text)
                if val > 10_000_000_000:
                    return val / 1000.0
                return val
            from datetime import datetime

            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except _SUPPRESSIBLE_EXCEPTIONS:
            return time.time()

    @staticmethod
    def _extract_price(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            for key in ("price", "markPrice", "lastPrice"):
                if key in value:
                    try:
                        return float(value[key])
                    except (TypeError, ValueError):
                        continue
        return 0.0

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


__all__ = [
    "ListingSniper",
    "ListingSniperConfig",
    "ListingOpportunity",
    "load_listing_sniper_config",
]
