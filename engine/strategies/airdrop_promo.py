from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from engine.core.market_resolver import resolve_market_choice
from engine.core.order_router import OrderRouter
from engine.execution.execute import StrategyExecutor
from engine.risk import RiskRails

try:  # Optional when metrics are disabled in certain test contexts
    from engine.metrics import (
        airdrop_cooldown_epoch,
        airdrop_events_total,
        airdrop_expected_value_usd,
        airdrop_orders_total,
    )
except ImportError:  # pragma: no cover - metrics disabled
    airdrop_events_total = None  # type: ignore[assignment]
    airdrop_orders_total = None  # type: ignore[assignment]
    airdrop_cooldown_epoch = None  # type: ignore[assignment]
    airdrop_expected_value_usd = None  # type: ignore[assignment]

_LOG = logging.getLogger("engine.strategies.airdrop_promo")
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
_BUS_EXCEPTIONS = _SUPPRESSIBLE_EXCEPTIONS + (ImportError,)


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOG.debug("%s suppressed: %s", context, exc, exc_info=True)


_QUOTE_REQUIREMENT_RE = re.compile(
    r"(?:trade|trading|volume|spend|buy)\s+(?:at\s+least\s+|minimum\s+of\s+|>=\s*)?"
    r"(?P<prefix>\$|usd|usdt|busd|fdusd|tusd)?\s*"
    r"(?P<amount>[\d,_]+(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>usd|usdt|busd|fdusd|tusd|dollars?))?",
    re.IGNORECASE,
)
_BASE_REQUIREMENT_RE = re.compile(
    r"(?:trade|trading|buy|hold)\s+(?:at\s+least\s+|minimum\s+of\s+|>=\s*)?([\d,_]+(?:\.\d+)?)\s*([A-Z]{2,10})",
    re.IGNORECASE,
)
_REWARD_RE = re.compile(
    r"(?:receive|get|earn|airdrop of|bonus of)\s+(?:up to\s+)?\$?\s*([\d,_]+(?:\.\d+)?)\s*(?:usd|usdt|busd|fdusd|tusd|dollars?)",
    re.IGNORECASE,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list(name: str, default: Iterable[str]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        return tuple(default)
    return tuple(items)


@dataclass(frozen=True)
class AirdropPromoConfig:
    enabled: bool = False
    dry_run: bool = True
    per_trade_risk_pct: float = 0.004  # ~0.4% of equity allocated per campaign
    fallback_equity_usd: float = 2_000.0
    default_notional_usd: float = 50.0
    notional_min_usd: float = 25.0
    notional_max_usd: float = 300.0
    min_expected_reward_usd: float = 8.0
    min_priority: float = 0.7
    max_spread_pct: float = 0.04
    cooldown_sec: float = 7200.0
    keywords: tuple[str, ...] = (
        "airdrop",
        "promotion",
        "launchpool",
        "launchpad",
        "reward",
        "campaign",
        "earn",
        "voucher",
    )
    deny_keywords: tuple[str, ...] = ("scam", "phishing")
    allowed_sources: tuple[str, ...] = ()
    metrics_enabled: bool = True
    publish_topic: str = "strategy.airdrop_promo_participation"
    default_market: str = "spot"


def load_airdrop_promo_config() -> AirdropPromoConfig:
    default_market_raw = os.getenv("AIRDROP_PROMO_DEFAULT_MARKET", "").strip().lower()
    default_market = default_market_raw or "spot"
    if default_market not in {"spot", "margin", "futures", "options"}:
        default_market = "spot"
    return AirdropPromoConfig(
        enabled=_env_bool("AIRDROP_PROMO_ENABLED", False),
        dry_run=_env_bool("AIRDROP_PROMO_DRY_RUN", True),
        per_trade_risk_pct=_env_float("AIRDROP_PROMO_RISK_PCT", 0.004),
        fallback_equity_usd=_env_float("AIRDROP_PROMO_FALLBACK_EQUITY", 2_000.0),
        default_notional_usd=_env_float("AIRDROP_PROMO_DEFAULT_NOTIONAL", 50.0),
        notional_min_usd=_env_float("AIRDROP_PROMO_NOTIONAL_MIN", 25.0),
        notional_max_usd=_env_float("AIRDROP_PROMO_NOTIONAL_MAX", 300.0),
        min_expected_reward_usd=_env_float("AIRDROP_PROMO_MIN_REWARD", 8.0),
        min_priority=_env_float("AIRDROP_PROMO_MIN_PRIORITY", 0.7),
        max_spread_pct=_env_float("AIRDROP_PROMO_MAX_SPREAD_PCT", 0.04),
        cooldown_sec=_env_float("AIRDROP_PROMO_COOLDOWN_SEC", 7200.0),
        keywords=_env_list(
            "AIRDROP_PROMO_KEYWORDS",
            (
                "airdrop",
                "promotion",
                "launchpool",
                "launchpad",
                "reward",
                "campaign",
                "earn",
                "voucher",
            ),
        ),
        deny_keywords=_env_list("AIRDROP_PROMO_DENY_KEYWORDS", ("scam", "phishing")),
        allowed_sources=_env_list("AIRDROP_PROMO_ALLOWED_SOURCES", ()),
        metrics_enabled=_env_bool("AIRDROP_PROMO_METRICS_ENABLED", True),
        publish_topic=os.getenv(
            "AIRDROP_PROMO_PUBLISH_TOPIC", "strategy.airdrop_promo_participation"
        ),
        default_market=default_market,
    )


class AirdropPromoWatcher:
    """
    Watches Binance announcements and external feeds for trading promotions / airdrops.

    The module implements the opportunistic flow described in the comprehensive
    framework doc: detect campaigns requiring a minimum trading volume, size the
    qualifying trade conservatively, and execute only when spreads/risk guardrails
    allow. Participation events can optionally be published back onto the event bus
    for observability or downstream automation (e.g. reminders to unwind inventory).
    """

    def __init__(
        self,
        router: OrderRouter,
        risk: RiskRails,
        rest_client: Any,
        cfg: AirdropPromoConfig | None = None,
        *,
        clock=time,
    ) -> None:
        self.router = router
        self.risk = risk
        self.rest_client = rest_client
        self.cfg = cfg or load_airdrop_promo_config()
        self.clock = clock
        self._cooldowns: dict[str, float] = {}
        self._seen_promos: set[str] = set()
        self._allow_sources = {src.lower() for src in self.cfg.allowed_sources if src}
        self._executor = StrategyExecutor(
            risk=risk,
            router=router,
            default_dry_run=self.cfg.dry_run,
            source="airdrop_promo",
        )

    # ------------------------------------------------------------------ public API
    async def on_external_event(self, evt: dict[str, Any]) -> None:
        if not self.cfg.enabled:
            return

        source = str(evt.get("source") or "").lower()
        if self._allow_sources and source not in self._allow_sources:
            return

        payload = evt.get("payload") or {}
        text_blob = self._combine_text(payload)
        if not text_blob:
            return

        lowered = text_blob.lower()
        if not any(keyword.lower() in lowered for keyword in self.cfg.keywords):
            return
        if any(term.lower() in lowered for term in self.cfg.deny_keywords):
            self._record_event("unknown", "deny_keyword")
            return

        priority = self._priority(evt)
        if priority < float(self.cfg.min_priority):
            self._record_event("unknown", "priority_low")
            return

        symbol = self._select_symbol(evt, payload)
        if not symbol:
            self._record_event("unknown", "no_symbol")
            return

        promo_id = self._promo_identifier(evt, payload, text_blob)
        if promo_id in self._seen_promos:
            self._record_event(symbol, "already_seen")
            return

        now = float(self.clock.time())
        if self._cooldown_active(symbol, now):
            self._record_event(symbol, "cooldown_active")
            return

        price_snapshot = await self._price_snapshot(symbol)
        if price_snapshot is None:
            self._record_event(symbol, "no_price")
            return
        price, spread = price_snapshot
        if spread > float(self.cfg.max_spread_pct):
            self._record_event(symbol, "spread_high")
            return

        quote_requirement, qty_requirement = self._extract_requirements(text_blob, symbol)
        expected_reward = self._extract_expected_reward(text_blob)
        if expected_reward is not None and expected_reward < float(
            self.cfg.min_expected_reward_usd
        ):
            self._record_event(symbol, "reward_low")
            self._seen_promos.add(promo_id)
            return

        notional = self._calc_notional(price, quote_requirement, qty_requirement)
        if notional <= 0:
            self._record_event(symbol, "sizing_failed")
            self._seen_promos.add(promo_id)
            return

        qualified_symbol = f"{symbol}.BINANCE" if "." not in symbol else symbol
        market_choice = resolve_market_choice(qualified_symbol, self.cfg.default_market)
        try:
            execution = await self._executor.execute(
                {
                    "strategy": "airdrop_promo",
                    "symbol": qualified_symbol,
                    "side": "BUY",
                    "quote": notional,
                    "market": market_choice,
                    "meta": {
                        "promo_id": promo_id,
                        "expected_reward": expected_reward,
                    },
                    "tag": "airdrop_entry",
                    "ts": now,
                }
            )
        except Exception as exc:
            _LOG.warning("[AIRDROP] execution failed for %s: %s", symbol, exc)
            self._record_order(symbol, "failed")
            self._set_cooldown(symbol, now)
            return

        status = str(execution.get("status") or "unknown")
        if status == "rejected":
            detail = str(execution.get("error") or execution.get("reason") or "risk")
            self._record_event(symbol, f"risk_{detail.lower()}")
            self._seen_promos.add(promo_id)
            self._set_cooldown(symbol, now)
            return

        self._record_event(symbol, "accepted")
        if expected_reward and airdrop_expected_value_usd:
            try:
                airdrop_expected_value_usd.labels(symbol=symbol).set(float(expected_reward))
            except Exception as exc:
                _log_suppressed("airdrop.expected_reward_metric", exc)

        self._seen_promos.add(promo_id)

        if status == "dry_run":
            _LOG.info(
                "[AIRDROP] dry-run: promo=%s symbol=%s quote=%.2f reward=%.2f market=%s",
                promo_id,
                symbol,
                notional,
                expected_reward or 0.0,
                market_choice,
            )
            self._record_order(symbol, "simulated")
            self._set_cooldown(symbol, now)
            await self._publish_participation(
                symbol,
                notional,
                price,
                expected_reward,
                promo_id,
                payload,
                dry_run=True,
                market=market_choice,
            )
            return

        order_payload = execution.get("order", {})
        router_result = order_payload.get("result", {})
        avg_px = self._safe_float(router_result.get("avg_fill_price"), default=price)
        qty = self._safe_float(
            router_result.get("filled_qty_base"), default=notional / max(avg_px, 1e-9)
        )
        _LOG.info(
            "[AIRDROP] participated promo=%s symbol=%s qty=%.6f avg=%.6f notional=%.2f reward=%.2f market=%s",
            promo_id,
            symbol,
            qty,
            avg_px,
            notional,
            expected_reward or 0.0,
            market_choice,
        )
        self._record_order(symbol, "filled")
        self._set_cooldown(symbol, now)
        await self._publish_participation(
            symbol,
            notional,
            avg_px,
            expected_reward,
            promo_id,
            payload,
            dry_run=False,
            market=market_choice,
        )

    async def shutdown(self) -> None:
        """Placeholder for symmetry with other strategies."""
        self._cooldowns.clear()
        self._seen_promos.clear()

    # ------------------------------------------------------------------ helpers
    def _priority(self, evt: dict[str, Any]) -> float:
        priority = evt.get("priority")
        if priority is None:
            priority = evt.get("payload", {}).get("priority")
        try:
            return float(priority if priority is not None else 0.5)
        except (TypeError, ValueError):
            return 0.5

    def _combine_text(self, payload: dict[str, Any]) -> str:
        parts = [
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("text") or ""),
            str(payload.get("content") or ""),
            str(payload.get("description") or ""),
        ]
        return " ".join(part for part in parts if part).strip()

    def _promo_identifier(self, evt: dict[str, Any], payload: dict[str, Any], text: str) -> str:
        fields = [
            payload.get("id"),
            payload.get("article_id"),
            payload.get("articleId"),
            payload.get("url"),
            payload.get("linkUrl"),
            evt.get("id"),
        ]
        for field in fields:
            if field:
                return str(field)
        return hex(abs(hash(text)))  # deterministic-ish fallback

    def _select_symbol(self, evt: dict[str, Any], payload: dict[str, Any]) -> str | None:
        candidates = []
        hints = evt.get("asset_hints") or []
        if isinstance(hints, list):
            candidates.extend([str(item or "") for item in hints])
        for key in ("tickers", "symbols", "assets", "pairs"):
            if key in payload and isinstance(payload[key], (list, tuple)):
                candidates.extend([str(item or "") for item in payload[key]])

        for cand in candidates:
            symbol = cand.strip().upper()
            if not symbol:
                continue
            if "." in symbol:
                base, venue = symbol.split(".", 1)
                if not base:
                    continue
                venue = venue or "BINANCE"
                if base.endswith(("USDT", "BUSD", "FDUSD", "TUSD", "USD")):
                    return f"{base}.{venue}"
                return f"{base}USDT.{venue}"
            if symbol.endswith(("USDT", "BUSD", "FDUSD", "TUSD")):
                return symbol
            if 3 <= len(symbol) <= 10:
                return f"{symbol}USDT"
        return None

    def _extract_requirements(
        self,
        text: str,
        symbol: str,
    ) -> tuple[float | None, float | None]:
        quote_requirement: float | None = None
        for match in _QUOTE_REQUIREMENT_RE.finditer(text):
            prefix = (match.group("prefix") or "").strip().lower()
            suffix = (match.group("suffix") or "").strip().lower()
            if not prefix and not suffix:
                continue
            try:
                amount = match.group("amount") or ""
                quote_requirement = float(amount.replace(",", "").replace("_", ""))
                break
            except (TypeError, ValueError):
                continue

        qty_requirement: float | None = None
        for match in _BASE_REQUIREMENT_RE.finditer(text):
            token = (match.group(2) or "").upper()
            if token in {"USD", "USDT", "BUSD", "FDUSD", "TUSD"}:
                continue
            try:
                qty_requirement = float(match.group(1).replace(",", "").replace("_", ""))
            except (TypeError, ValueError):
                continue
            base = symbol.split(".")[0]
            if base and token.endswith("USDT"):
                token = token[:-4]
            if base and token and token != base.rstrip("USDT"):
                # Requirement references a different token; skip
                qty_requirement = None
                continue
            break

        return quote_requirement, qty_requirement

    def _extract_expected_reward(self, text: str) -> float | None:
        match = _REWARD_RE.search(text)
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", "").replace("_", ""))
        except (TypeError, ValueError):
            return None

    def _calc_notional(
        self,
        price: float,
        quote_requirement: float | None,
        qty_requirement: float | None,
    ) -> float:
        equity = self._router_equity()
        if equity <= 0:
            equity = float(self.cfg.fallback_equity_usd)
        risk_budget = equity * float(self.cfg.per_trade_risk_pct)
        notional = max(risk_budget, float(self.cfg.default_notional_usd))

        if quote_requirement:
            notional = max(notional, float(quote_requirement))
        if qty_requirement:
            notional = max(notional, float(qty_requirement) * price)

        notional = max(float(self.cfg.notional_min_usd), notional)
        notional = min(float(self.cfg.notional_max_usd), notional)
        return float(notional)

    def _router_equity(self) -> float:
        try:
            return float(self.router._portfolio.state.equity)  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError):
            return 0.0

    async def _price_snapshot(self, symbol: str) -> tuple[float, float] | None:
        client = self.rest_client
        if client is None:
            return None

        price = 0.0
        spread = 0.0
        book_fn = getattr(client, "book_ticker", None)
        if callable(book_fn):
            book = book_fn(symbol)
            if inspect.isawaitable(book):
                book = await book
            if isinstance(book, dict):
                bid = self._safe_float(book.get("bidPrice"))
                ask = self._safe_float(book.get("askPrice"))
                if bid > 0 and ask > 0:
                    price = (bid + ask) / 2.0
                    spread = abs(ask - bid) / max(price, 1e-9)
        if price <= 0:
            px_fn = getattr(client, "ticker_price", None)
            if callable(px_fn):
                res = px_fn(symbol)
                if inspect.isawaitable(res):
                    res = await res
                price = self._safe_float(res)
        return (price, spread) if price > 0 else None

    def _cooldown_active(self, symbol: str, now: float) -> bool:
        active_until = self._cooldowns.get(symbol)
        return bool(active_until and now < active_until)

    def _set_cooldown(self, symbol: str, now: float) -> None:
        expiry = now + float(self.cfg.cooldown_sec)
        self._cooldowns[symbol] = expiry
        if self.cfg.metrics_enabled and airdrop_cooldown_epoch:
            try:
                airdrop_cooldown_epoch.labels(symbol=symbol).set(expiry)
            except Exception as exc:
                _log_suppressed("airdrop.cooldown_metric", exc)

    async def _publish_participation(
        self,
        symbol: str,
        notional_usd: float,
        reference_price: float,
        expected_reward: float | None,
        promo_id: str,
        payload: dict[str, Any],
        *,
        dry_run: bool,
        market: str = "spot",
    ) -> None:
        topic = self.cfg.publish_topic
        if not topic:
            return
        data = {
            "promo_id": promo_id,
            "symbol": symbol,
            "notional_usd": notional_usd,
            "reference_price": reference_price,
            "expected_reward_usd": expected_reward,
            "dry_run": dry_run,
            "ts": int(self.clock.time() * 1000),
            "source_payload": payload,
            "market": market,
        }
        try:
            from engine.core.event_bus import BUS

            BUS.fire(topic, data)
        except _BUS_EXCEPTIONS as exc:
            _log_suppressed("airdrop.publish_participation", exc)

    def _record_event(self, symbol: str, decision: str) -> None:
        if not self.cfg.metrics_enabled or not airdrop_events_total:
            return
        try:
            airdrop_events_total.labels(symbol=symbol, decision=decision).inc()
        except Exception as exc:
            _log_suppressed("airdrop.event_metric", exc)

    def _record_order(self, symbol: str, status: str) -> None:
        if not self.cfg.metrics_enabled or not airdrop_orders_total:
            return
        try:
            airdrop_orders_total.labels(symbol=symbol, status=status).inc()
        except Exception as exc:
            _log_suppressed("airdrop.order_metric", exc)

    @staticmethod
    def _safe_float(value: Any, *, default: float = 0.0) -> float:
        try:
            if isinstance(value, dict):
                value = value.get("price") or value.get("avgPrice")
            return float(value)
        except (TypeError, ValueError):
            return default


__all__ = [
    "AirdropPromoWatcher",
    "AirdropPromoConfig",
    "load_airdrop_promo_config",
]
