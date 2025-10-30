from __future__ import annotations

import inspect
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

from engine.config.defaults import MEME_SENTIMENT_DEFAULTS
from engine.config.env import env_bool, env_float, env_int, env_str, env_csv
from engine.core.order_router import OrderRouter
from engine.core.market_resolver import resolve_market_choice
from engine.risk import RiskRails

try:  # Metrics are optional in some test contexts
    from engine.metrics import (
        meme_sentiment_events_total,
        meme_sentiment_orders_total,
        meme_sentiment_cooldown_epoch,
    )
except Exception:  # pragma: no cover - metrics disabled
    meme_sentiment_events_total = None  # type: ignore[assignment]
    meme_sentiment_orders_total = None  # type: ignore[assignment]
    meme_sentiment_cooldown_epoch = None  # type: ignore[assignment]

_LOG = logging.getLogger("engine.strategies.meme_sentiment")
@dataclass(frozen=True)
class MemeCoinConfig:
    enabled: bool = False
    dry_run: bool = True
    per_trade_risk_pct: float = 0.0075  # ~0.75% of equity at risk
    stop_loss_pct: float = 0.10
    take_profit_pct: float = 0.25
    trail_stop_pct: float = 0.12
    fallback_equity_usd: float = 2_000.0
    notional_min_usd: float = 25.0
    notional_max_usd: float = 200.0
    min_priority: float = 0.82
    min_social_score: float = 2.2
    min_mentions: int = 18
    min_velocity_score: float = 1.0
    max_chase_pct: float = 0.55
    max_spread_pct: float = 0.035
    cooldown_sec: float = 1_200.0
    trade_lock_sec: float = 600.0
    deny_keywords: Tuple[str, ...] = ("rug", "rugpull", "scam", "honeypot")
    allow_sources: Tuple[str, ...] = ()
    quote_priority: Tuple[str, ...] = ("USDT", "USDC", "BUSD")
    metrics_enabled: bool = True
    publish_topic: str = "strategy.meme_sentiment_trade"
    default_market: str = "spot"


def load_meme_coin_config() -> MemeCoinConfig:
    if os.environ.get("SOCIAL_SENTIMENT_ENABLED") and not os.environ.get("MEME_SENTIMENT_ENABLED"):
        os.environ["MEME_SENTIMENT_ENABLED"] = os.environ["SOCIAL_SENTIMENT_ENABLED"]
        _LOG.warning("SOCIAL_SENTIMENT_ENABLED is deprecated; use MEME_SENTIMENT_ENABLED instead")
    if os.environ.get("SOCIAL_SENTIMENT_SOURCES") and not os.environ.get("MEME_SENTIMENT_SOURCES"):
        os.environ["MEME_SENTIMENT_SOURCES"] = os.environ["SOCIAL_SENTIMENT_SOURCES"]
        _LOG.warning("SOCIAL_SENTIMENT_SOURCES is deprecated; use MEME_SENTIMENT_SOURCES instead")

    default_market_raw = env_str(
        "MEME_SENTIMENT_DEFAULT_MARKET",
        MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_DEFAULT_MARKET"],
    ).strip().lower()
    default_market = default_market_raw or "spot"
    if default_market not in {"spot", "margin", "futures", "options"}:
        default_market = "spot"
    return MemeCoinConfig(
        enabled=env_bool("MEME_SENTIMENT_ENABLED", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_ENABLED"]),
        dry_run=env_bool("MEME_SENTIMENT_DRY_RUN", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_DRY_RUN"]),
        per_trade_risk_pct=env_float("MEME_SENTIMENT_RISK_PCT", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_RISK_PCT"]),
        stop_loss_pct=env_float("MEME_SENTIMENT_STOP_PCT", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_STOP_PCT"]),
        take_profit_pct=env_float("MEME_SENTIMENT_TP_PCT", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_TP_PCT"]),
        trail_stop_pct=env_float("MEME_SENTIMENT_TRAIL_PCT", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_TRAIL_PCT"]),
        fallback_equity_usd=env_float("MEME_SENTIMENT_FALLBACK_EQUITY", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_FALLBACK_EQUITY"]),
        notional_min_usd=env_float("MEME_SENTIMENT_NOTIONAL_MIN", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_NOTIONAL_MIN"]),
        notional_max_usd=env_float("MEME_SENTIMENT_NOTIONAL_MAX", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_NOTIONAL_MAX"]),
        min_priority=env_float("MEME_SENTIMENT_MIN_PRIORITY", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_MIN_PRIORITY"]),
        min_social_score=env_float("MEME_SENTIMENT_MIN_SCORE", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_MIN_SCORE"]),
        min_mentions=env_int("MEME_SENTIMENT_MIN_MENTIONS", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_MIN_MENTIONS"]),
        min_velocity_score=env_float("MEME_SENTIMENT_MIN_VELOCITY", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_MIN_VELOCITY"]),
        max_chase_pct=env_float("MEME_SENTIMENT_MAX_CHASE_PCT", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_MAX_CHASE_PCT"]),
        max_spread_pct=env_float("MEME_SENTIMENT_MAX_SPREAD_PCT", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_MAX_SPREAD_PCT"]),
        cooldown_sec=env_float("MEME_SENTIMENT_COOLDOWN_SEC", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_COOLDOWN_SEC"]),
        trade_lock_sec=env_float("MEME_SENTIMENT_LOCK_SEC", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_LOCK_SEC"]),
        deny_keywords=tuple(env_csv("MEME_SENTIMENT_DENY_KEYWORDS", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_DENY_KEYWORDS"])),
        allow_sources=tuple(env_csv("MEME_SENTIMENT_SOURCES", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_SOURCES"])),
        quote_priority=tuple(env_csv("MEME_SENTIMENT_QUOTES", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_QUOTES"])),
        metrics_enabled=env_bool("MEME_SENTIMENT_METRICS_ENABLED", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_METRICS_ENABLED"]),
        publish_topic=env_str("MEME_SENTIMENT_PUBLISH_TOPIC", MEME_SENTIMENT_DEFAULTS["MEME_SENTIMENT_PUBLISH_TOPIC"]),
        default_market=default_market,
    )


@dataclass
class _ScoreMeta:
    score: float
    mentions: float
    velocity: float
    sentiment: float
    price_change: float
    priority: float
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class MemeCoinSentiment:
    """
    Event-driven meme coin strategy reacting to social sentiment spikes.

    The module listens to ``events.external_feed`` payloads emitted by external
    connectors (Twitter firehose, Reddit scrapers, sentiment APIs). It applies
    guardrails defined in ``docs/Comprehensive Framework for a Binance Crypto Trading Bot.md``:

      * small fixed-risk sizing (0.5–1% of equity) solved via per-trade risk pct
      * strict cooldowns and global lock to avoid stacking correlated trades
      * sentiment/velocity thresholds so only explosive meme events trigger
      * stop / take-profit / trailing guidelines published alongside the fill
    """

    def __init__(
        self,
        router: OrderRouter,
        risk: RiskRails,
        rest_client: Any,
        cfg: Optional[MemeCoinConfig] = None,
        *,
        clock=time,
    ) -> None:
        self.router = router
        self.risk = risk
        self.rest_client = rest_client
        self.cfg = cfg or load_meme_coin_config()
        self.clock = clock
        self._cooldowns: Dict[str, float] = {}
        self._global_lock_until: float = 0.0
        self._allow_sources = {src.lower() for src in self.cfg.allow_sources}

    # ------------------------------------------------------------------ public
    async def on_external_event(self, evt: Dict[str, Any]) -> None:
        if not self.cfg.enabled:
            return
        source = str(evt.get("source") or "").lower()
        if self._allow_sources and source not in self._allow_sources:
            return

        symbol = self._select_symbol(evt)
        if not symbol:
            self._record_event("unknown", "no_symbol")
            return

        now = self.clock.time()
        if now < self._global_lock_until:
            self._record_event(symbol, "global_lock")
            return
        if self._cooldown_active(symbol, now):
            self._record_event(symbol, "cooldown_active")
            return

        if not self._passes_priority(evt):
            self._record_event(symbol, "priority_low")
            return
        if self._contains_banned_terms(evt):
            self._record_event(symbol, "deny_keyword")
            return

        score_meta = self._score_event(evt)
        if score_meta.score < self.cfg.min_social_score:
            self._record_event(symbol, "score_low")
            return
        if score_meta.mentions < float(self.cfg.min_mentions):
            self._record_event(symbol, "mentions_low")
            return
        if score_meta.velocity < float(self.cfg.min_velocity_score):
            self._record_event(symbol, "velocity_low")
            return

        price_info = await self._price_snapshot(symbol)
        if price_info is None:
            self._record_event(symbol, "no_price")
            return
        price, spread = price_info
        if price <= 0:
            self._record_event(symbol, "no_price")
            return
        if spread > self.cfg.max_spread_pct:
            self._record_event(symbol, "spread_high")
            return

        move = max(score_meta.price_change, score_meta.raw_payload.get("price_change_event", 0.0))
        if move > self.cfg.max_chase_pct:
            self._record_event(symbol, "chase")
            return

        notional = self._calc_notional()
        if notional <= 0:
            self._record_event(symbol, "sizing_failed")
            return

        full_symbol = f"{symbol}.BINANCE"
        market_choice = resolve_market_choice(full_symbol, self.cfg.default_market)
        ok, err = self.risk.check_order(symbol=full_symbol, side="BUY", quote=notional, quantity=None, market=market_choice)
        if not ok:
            reason = str(err.get("error") or "risk")
            self._record_event(symbol, f"risk_{reason.lower()}")
            self._set_cooldown(symbol, now)
            return

        self._record_event(symbol, "accepted")

        if self.cfg.dry_run:
            _LOG.info(
                "[MEME] dry-run BUY %s notional=%.2f score=%.2f priority=%.2f mentions=%.1f velocity=%.2f market=%s",
                symbol,
                notional,
                score_meta.score,
                score_meta.priority,
                score_meta.mentions,
                score_meta.velocity,
                market_choice,
            )
            self._record_order(symbol, "simulated")
            self._set_cooldown(symbol, now)
            self._arm_global_lock(now)
            return

        try:
            result = await self.router.market_quote(full_symbol, "BUY", notional, market=market_choice)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("[MEME] execution failed for %s: %s", symbol, exc)
            self._record_order(symbol, "failed")
            self._set_cooldown(symbol, now)
            self._arm_global_lock(now)
            return

        avg_px = self._as_float(result.get("avg_fill_price")) or price
        qty = self._as_float(result.get("filled_qty_base")) or (notional / max(avg_px, 1e-9))
        _LOG.info(
            "[MEME] executed BUY %s notional=%.2f qty=%.6f avg=%.6f score=%.2f market=%s",
            symbol,
            notional,
            qty,
            avg_px,
            score_meta.score,
            market_choice,
        )
        self._record_order(symbol, "filled")
        await self._publish_trade(symbol, qty, avg_px, score_meta, market_choice)

        stop_px = avg_px * max(0.0001, 1.0 - self.cfg.stop_loss_pct)
        tp_px = avg_px * (1.0 + self.cfg.take_profit_pct)
        trail_px = avg_px * max(0.0001, 1.0 - self.cfg.trail_stop_pct)
        await self._publish_bracket(symbol, qty, avg_px, stop_px, tp_px, trail_px, score_meta, market_choice)

        self._set_cooldown(symbol, now)
        self._arm_global_lock(now)

    # ----------------------------------------------------------------- helpers
    def _passes_priority(self, evt: Dict[str, Any]) -> bool:
        priority = evt.get("priority")
        if priority is None:
            priority = evt.get("payload", {}).get("priority")
        if priority is None:
            priority = 0.5
        try:
            return float(priority) >= float(self.cfg.min_priority)
        except (TypeError, ValueError):
            return False

    def _contains_banned_terms(self, evt: Dict[str, Any]) -> bool:
        payload = evt.get("payload") or {}
        text_parts = [
            str(payload.get("text") or ""),
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
        ]
        text = " ".join(text_parts).lower()
        return any(term.lower() in text for term in self.cfg.deny_keywords)

    def _score_event(self, evt: Dict[str, Any]) -> _ScoreMeta:
        payload = evt.get("payload") or {}
        metrics = payload.get("metrics") or {}

        mentions = self._as_float(payload.get("mentions"))
        mentions = max(mentions, self._as_float(payload.get("mention_count")))
        mentions = max(mentions, self._as_float(metrics.get("mention_count")))
        likes = self._as_float(metrics.get("like_count") or metrics.get("favorite_count"))
        retweets = self._as_float(metrics.get("retweet_count"))
        quotes = self._as_float(metrics.get("quote_count"))
        replies = self._as_float(metrics.get("reply_count") or payload.get("comment_count"))

        interactions = mentions + (retweets * 1.8) + (likes * 0.35) + (quotes * 0.5) + (replies * 0.8)
        interactions = max(interactions, 0.0)

        velocity_raw = self._as_float(payload.get("social_velocity") or payload.get("velocity") or payload.get("social_volume_change_pct"))
        velocity_raw = max(velocity_raw, self._as_float(metrics.get("velocity") or metrics.get("social_velocity")))
        velocity_raw = max(velocity_raw, 0.0)
        velocity_score = math.log1p(velocity_raw)

        sentiment = self._as_float(payload.get("sentiment_score") or payload.get("sentiment") or metrics.get("sentiment_score"))
        sentiment = max(min(sentiment, 1.5), -1.5)

        price_change_pct = payload.get("price_change_pct")
        price_change_pct = self._as_float(price_change_pct if price_change_pct is not None else payload.get("price_change_5m_pct"))
        price_change_pct = self._normalize_pct(price_change_pct)

        priority = self._as_float(evt.get("priority") or payload.get("priority") or 0.5)

        mention_score = math.log1p(interactions)
        price_score = math.log1p(max(price_change_pct, 0.0))
        sentiment_multiplier = 1.0
        if sentiment > 0:
            sentiment_multiplier += min(sentiment, 1.0) * 0.6
        else:
            sentiment_multiplier += max(sentiment, -1.0) * 0.4

        score = (mention_score * 0.5) + (velocity_score * 0.3) + (price_score * 0.2)
        score *= sentiment_multiplier
        score *= max(0.55, priority)

        meta_payload = {
            "mentions_raw": interactions,
            "likes": likes,
            "retweets": retweets,
            "quotes": quotes,
            "replies": replies,
        }
        meta = _ScoreMeta(
            score=score,
            mentions=interactions,
            velocity=velocity_raw,
            sentiment=sentiment,
            price_change=price_change_pct,
            priority=priority,
            raw_payload=meta_payload,
        )
        return meta

    def _calc_notional(self) -> float:
        equity = self._router_equity()
        if equity <= 0:
            equity = float(self.cfg.fallback_equity_usd)
        risk_budget = equity * float(self.cfg.per_trade_risk_pct)
        notional = risk_budget / max(self.cfg.stop_loss_pct, 1e-6)
        notional = max(self.cfg.notional_min_usd, min(self.cfg.notional_max_usd, notional))
        return float(notional)

    def _router_equity(self) -> float:
        try:
            return float(self.router._portfolio.state.equity)  # type: ignore[attr-defined]
        except Exception:
            return 0.0

    async def _price_snapshot(self, symbol: str) -> Optional[Tuple[float, float]]:
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
                bid = self._as_float(book.get("bidPrice"))
                ask = self._as_float(book.get("askPrice"))
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
        return (price, spread) if price > 0 else None

    async def _publish_trade(
        self,
        symbol: str,
        qty: float,
        avg_px: float,
        score: _ScoreMeta,
        market: str = "spot",
    ) -> None:
        topic = self.cfg.publish_topic
        if not topic:
            return
        payload = {
            "symbol": symbol,
            "side": "BUY",
            "qty": qty,
            "avg_price": avg_px,
            "score": score.score,
            "mentions": score.mentions,
            "velocity": score.velocity,
            "sentiment": score.sentiment,
            "price_change": score.price_change,
            "priority": score.priority,
            "ts": int(self.clock.time() * 1000),
            "market": market,
        }
        try:
            from engine.core.event_bus import BUS

            await BUS.publish(topic, payload)
        except Exception:
            # Publishing is best-effort; do not raise.
            pass

    async def _publish_bracket(
        self,
        symbol: str,
        qty: float,
        avg_px: float,
        stop_px: float,
        tp_px: float,
        trail_px: float,
        score: _ScoreMeta,
        market: str = "spot",
    ) -> None:
        meta = {
            "symbol": symbol,
            "qty": qty,
            "avg_price": avg_px,
            "stop_price": stop_px,
            "take_profit": tp_px,
            "trail_price": trail_px,
            "score": score.score,
            "market": market,
        }
        try:
            from engine.core.event_bus import BUS

            await BUS.publish(
                "strategy.meme_sentiment_bracket",
                meta,
            )
        except Exception:
            pass

    def _set_cooldown(self, symbol: str, now: Optional[float] = None) -> None:
        if self.cfg.cooldown_sec <= 0:
            return
        now = now or self.clock.time()
        until = now + float(self.cfg.cooldown_sec)
        self._cooldowns[symbol] = until
        if self.cfg.metrics_enabled and meme_sentiment_cooldown_epoch is not None:
            try:
                meme_sentiment_cooldown_epoch.labels(symbol=symbol).set(until)
            except Exception:
                pass

    def _cooldown_active(self, symbol: str, now: float) -> bool:
        until = self._cooldowns.get(symbol)
        if not until:
            return False
        if now >= until:
            self._cooldowns.pop(symbol, None)
            return False
        return True

    def _arm_global_lock(self, now: float) -> None:
        if self.cfg.trade_lock_sec <= 0:
            return
        self._global_lock_until = max(self._global_lock_until, now + float(self.cfg.trade_lock_sec))

    def _record_event(self, symbol: str, decision: str) -> None:
        if not self.cfg.metrics_enabled or meme_sentiment_events_total is None:
            return
        try:
            meme_sentiment_events_total.labels(symbol=symbol, decision=decision).inc()
        except Exception:
            pass

    def _record_order(self, symbol: str, status: str) -> None:
        if not self.cfg.metrics_enabled or meme_sentiment_orders_total is None:
            return
        try:
            meme_sentiment_orders_total.labels(symbol=symbol, status=status).inc()
        except Exception:
            pass

    def _select_symbol(self, evt: Dict[str, Any]) -> Optional[str]:
        hints = evt.get("asset_hints") or []
        payload = evt.get("payload") or {}
        if not hints:
            hints = self._extract_from_text(str(payload.get("text") or ""))
        for raw in hints:
            symbol = self._normalize_symbol(str(raw))
            if symbol:
                return symbol
        return None

    def _normalize_symbol(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        sym = raw.upper().strip()
        if "." in sym:
            sym = sym.split(".")[0]
        for quote in self.cfg.quote_priority:
            if sym.endswith(quote):
                base = sym[: -len(quote)] or ""
                if base and self._is_valid_base(base):
                    return f"{base}{quote}"
        if self.cfg.quote_priority:
            base = sym
            if self._is_valid_base(base):
                return f"{base}{self.cfg.quote_priority[0]}"
        return None

    def _is_valid_base(self, base: str) -> bool:
        if not base:
            return False
        if base.upper() in {"USDT", "USDC", "BUSD", "USD"}:
            return False
        if len(base) > 8:
            return False
        return True

    def _extract_from_text(self, text: str) -> Iterable[str]:
        if not text:
            return []
        matches = re.findall(r"#([A-Za-z0-9_]{2,15})", text)
        return [m.upper() for m in matches]

    @staticmethod
    def _normalize_pct(value: float) -> float:
        try:
            v = abs(float(value))
        except (TypeError, ValueError):
            return 0.0
        if v > 10:
            v = v / 100.0
        return v

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
    "MemeCoinConfig",
    "MemeCoinSentiment",
    "load_meme_coin_config",
]
