from __future__ import annotations

import inspect
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

from engine.core.market_resolver import resolve_market_choice
from engine.core.order_router import OrderRouter
from engine.risk import RiskRails

try:  # Metrics may not be available during unit tests
    from engine.metrics import (
        social_sentiment_cooldown_epoch,
        social_sentiment_events_total,
        social_sentiment_orders_total,
        social_sentiment_signal_score,
    )
except Exception:  # pragma: no cover - metrics optional in some environments
    social_sentiment_cooldown_epoch = None  # type: ignore[assignment]
    social_sentiment_events_total = None  # type: ignore[assignment]
    social_sentiment_orders_total = None  # type: ignore[assignment]
    social_sentiment_signal_score = None  # type: ignore[assignment]

_LOG = logging.getLogger("engine.strategies.social_sentiment")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_list(name: str, default: Iterable[str]) -> Tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(parts or default)


@dataclass(frozen=True)
class SocialSentimentConfig:
    enabled: bool = False
    dry_run: bool = True
    per_trade_risk_pct: float = 0.006  # ~0.6% of equity risked per idea
    stop_loss_pct: float = 0.09
    take_profit_pct: float = 0.22
    trail_stop_pct: float = 0.11
    take_profit_levels: Tuple[float, ...] = (0.35, 0.65)
    fallback_equity_usd: float = 2_500.0
    notional_min_usd: float = 25.0
    notional_max_usd: float = 250.0
    min_signal_score: float = 1.25
    min_mentions: float = 10.0
    min_velocity: float = 0.75
    min_sentiment: float = 0.18
    negative_sentiment_threshold: float = -0.4
    allow_shorts: bool = False
    max_chase_pct: float = 0.65
    max_spread_pct: float = 0.05
    max_event_age_sec: float = 90.0
    cooldown_sec: float = 900.0
    coin_cooldown_sec: float = 420.0
    global_cooldown_sec: float = 120.0
    deny_keywords: Tuple[str, ...] = ("hack", "scam", "rug", "exploit")
    allow_sources: Tuple[str, ...] = ()
    influencers: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()
    quote_priority: Tuple[str, ...] = ("USDT", "USDC", "BUSD")
    metrics_enabled: bool = True
    publish_topic: str = "strategy.social_sentiment_trade"
    default_market: str = "spot"


def load_social_sentiment_config() -> SocialSentimentConfig:
    default_market_raw = os.getenv("SOCIAL_SENTIMENT_DEFAULT_MARKET", "").strip().lower()
    default_market = default_market_raw or "spot"
    if default_market not in {"spot", "margin", "futures", "options"}:
        default_market = "spot"
    return SocialSentimentConfig(
        enabled=_env_bool("SOCIAL_SENTIMENT_ENABLED", False),
        dry_run=_env_bool("SOCIAL_SENTIMENT_DRY_RUN", True),
        per_trade_risk_pct=_env_float("SOCIAL_SENTIMENT_RISK_PCT", 0.006),
        stop_loss_pct=_env_float("SOCIAL_SENTIMENT_STOP_PCT", 0.09),
        take_profit_pct=_env_float("SOCIAL_SENTIMENT_TP_PCT", 0.22),
        trail_stop_pct=_env_float("SOCIAL_SENTIMENT_TRAIL_PCT", 0.11),
        take_profit_levels=tuple(
            float(level)
            for level in _env_list("SOCIAL_SENTIMENT_TP_LEVELS", ("0.35", "0.65"))
        ),
        fallback_equity_usd=_env_float("SOCIAL_SENTIMENT_FALLBACK_EQUITY", 2_500.0),
        notional_min_usd=_env_float("SOCIAL_SENTIMENT_NOTIONAL_MIN", 25.0),
        notional_max_usd=_env_float("SOCIAL_SENTIMENT_NOTIONAL_MAX", 250.0),
        min_signal_score=_env_float("SOCIAL_SENTIMENT_MIN_SCORE", 1.25),
        min_mentions=_env_float("SOCIAL_SENTIMENT_MIN_MENTIONS", 10.0),
        min_velocity=_env_float("SOCIAL_SENTIMENT_MIN_VELOCITY", 0.75),
        min_sentiment=_env_float("SOCIAL_SENTIMENT_MIN_SENTIMENT", 0.18),
        negative_sentiment_threshold=_env_float("SOCIAL_SENTIMENT_NEG_THRESHOLD", -0.4),
        allow_shorts=_env_bool("SOCIAL_SENTIMENT_ALLOW_SHORTS", False),
        max_chase_pct=_env_float("SOCIAL_SENTIMENT_MAX_CHASE_PCT", 0.65),
        max_spread_pct=_env_float("SOCIAL_SENTIMENT_MAX_SPREAD_PCT", 0.05),
        max_event_age_sec=_env_float("SOCIAL_SENTIMENT_EVENT_MAX_AGE", 90.0),
        cooldown_sec=_env_float("SOCIAL_SENTIMENT_COOLDOWN_SEC", 900.0),
        coin_cooldown_sec=_env_float("SOCIAL_SENTIMENT_COIN_COOLDOWN_SEC", 420.0),
        global_cooldown_sec=_env_float("SOCIAL_SENTIMENT_GLOBAL_LOCK_SEC", 120.0),
        deny_keywords=_env_list("SOCIAL_SENTIMENT_DENY_KEYWORDS", ("hack", "scam", "rug", "exploit")),
        allow_sources=_env_list("SOCIAL_SENTIMENT_SOURCES", ()),
        influencers=tuple(handle.lower() for handle in _env_list("SOCIAL_SENTIMENT_INFLUENCERS", ())),
        keywords=tuple(keyword.lower() for keyword in _env_list("SOCIAL_SENTIMENT_KEYWORDS", ())),
        quote_priority=_env_list("SOCIAL_SENTIMENT_QUOTES", ("USDT", "USDC", "BUSD")),
        metrics_enabled=_env_bool("SOCIAL_SENTIMENT_METRICS_ENABLED", True),
        publish_topic=os.getenv("SOCIAL_SENTIMENT_PUBLISH_TOPIC", "strategy.social_sentiment_trade"),
        default_market=default_market,
    )


@dataclass
class _SignalMeta:
    score: float
    mentions: float
    velocity: float
    sentiment: float
    price_change: float
    confidence: float
    engagement: float
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class SocialSentimentModule:
    """Trades on social-media driven impulses for meme and news catalysts."""

    def __init__(
        self,
        router: OrderRouter,
        risk: RiskRails,
        rest_client: Any,
        cfg: Optional[SocialSentimentConfig] = None,
        *,
        clock=time,
    ) -> None:
        self.router = router
        self.risk = risk
        self.rest_client = rest_client
        self.cfg = cfg or load_social_sentiment_config()
        self.clock = clock
        self._coin_cooldowns: Dict[str, float] = {}
        self._global_lock_until: float = 0.0
        self._allowed_sources = {src.lower() for src in self.cfg.allow_sources}
        self._deny_terms = {term.lower() for term in self.cfg.deny_keywords}
        self._influencers = {handle.lower().lstrip("@").strip() for handle in self.cfg.influencers}
        self._keywords = {kw.lower() for kw in self.cfg.keywords}

    async def on_external_event(self, evt: Dict[str, Any]) -> None:
        if not self.cfg.enabled:
            return

        now = self.clock.time()
        event_ts = self._event_timestamp(evt)
        if event_ts and (now - event_ts) > float(self.cfg.max_event_age_sec):
            self._record_event("unknown", "stale")
            return

        source = str(evt.get("source") or "").lower()
        if self._allowed_sources and source not in self._allowed_sources:
            self._record_event("unknown", "source_filtered")
            return

        symbol = self._select_symbol(evt)
        if not symbol:
            self._record_event("unknown", "no_symbol")
            return

        if now < self._global_lock_until:
            self._record_event(symbol, "global_cooldown")
            return

        if self._cooldown_active(symbol, now):
            self._record_event(symbol, "coin_cooldown")
            return

        text_blob = self._event_text(evt)
        if self._contains_deny_term(text_blob):
            self._record_event(symbol, "deny_keyword")
            return

        if self._keywords and not any(keyword in text_blob for keyword in self._keywords):
            self._record_event(symbol, "keyword_miss")
            return

        author = self._extract_author(evt)
        if self._influencers and author not in self._influencers:
            if not any(handle in text_blob for handle in self._influencers):
                self._record_event(symbol, "influencer_miss")
                return

        signal_meta = self._score_event(evt)
        self._record_score(symbol, signal_meta.score)

        if signal_meta.score < float(self.cfg.min_signal_score):
            self._record_event(symbol, "score_low")
            return
        if signal_meta.mentions < float(self.cfg.min_mentions):
            self._record_event(symbol, "mentions_low")
            return
        if signal_meta.velocity < float(self.cfg.min_velocity):
            self._record_event(symbol, "velocity_low")
            return

        direction = self._resolve_direction(signal_meta)
        if direction is None:
            self._record_event(symbol, "sentiment_neutral")
            return
        if direction == "SELL" and not self.cfg.allow_shorts:
            self._record_event(symbol, "short_blocked")
            return

        price_info = await self._price_snapshot(symbol)
        if price_info is None:
            self._record_event(symbol, "no_price")
            return
        price, spread = price_info
        if price <= 0:
            self._record_event(symbol, "no_price")
            return
        if spread > float(self.cfg.max_spread_pct):
            self._record_event(symbol, "spread_high")
            return
        if signal_meta.price_change > float(self.cfg.max_chase_pct):
            self._record_event(symbol, "chase")
            return

        notional = self._calc_notional()
        if notional <= 0:
            self._record_event(symbol, "sizing_failed")
            return

        qty = notional / max(price, 1e-9)
        if direction == "SELL" and qty <= 0:
            self._record_event(symbol, "sizing_failed")
            return

        full_symbol = f"{symbol}.BINANCE"
        market_choice = resolve_market_choice(full_symbol, self.cfg.default_market)
        quote_arg = notional if direction == "BUY" else None
        qty_arg = None if direction == "BUY" else qty

        ok, err = self.risk.check_order(
            symbol=full_symbol,
            side=direction,
            quote=quote_arg,
            quantity=qty_arg,
            market=market_choice,
        )
        if not ok:
            reason = str(err.get("error") if isinstance(err, dict) else err)
            self._record_event(symbol, f"risk_{reason or 'reject'}")
            self._set_coin_cooldown(symbol, now)
            self._arm_global_lock(now)
            return

        self._record_event(symbol, "accepted")

        if self.cfg.dry_run:
            _LOG.info(
                "[SOCIAL] dry-run %s %s notional=%.2f score=%.2f sentiment=%.2f mentions=%.1f market=%s",
                direction,
                symbol,
                notional,
                signal_meta.score,
                signal_meta.sentiment,
                signal_meta.mentions,
                market_choice,
            )
            self._record_order(symbol, "simulated")
            self._set_coin_cooldown(symbol, now)
            self._arm_global_lock(now)
            return

        try:
            if direction == "BUY":
                result = await self.router.market_quote(full_symbol, "BUY", notional, market=market_choice)
            else:
                result = await self.router.market_quantity(full_symbol, "SELL", qty, market=market_choice)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("[SOCIAL] execution failed for %s: %s", symbol, exc)
            self._record_order(symbol, "failed")
            self._set_coin_cooldown(symbol, now)
            self._arm_global_lock(now)
            return

        avg_px = self._as_float(result.get("avg_fill_price")) or price
        filled_qty = self._as_float(result.get("filled_qty_base")) or qty
        if filled_qty <= 0:
            filled_qty = qty if direction == "SELL" else notional / max(avg_px, 1e-9)

        _LOG.info(
            "[SOCIAL] executed %s %s qty=%.6f avg=%.6f score=%.2f market=%s",
            direction,
            symbol,
            filled_qty,
            avg_px,
            signal_meta.score,
            market_choice,
        )
        self._record_order(symbol, "filled")

        await self._publish_trade(symbol, direction, filled_qty, avg_px, signal_meta, market_choice)

        stop_px, target_levels, trail_px = self._build_exit_levels(direction, avg_px)
        await self._publish_bracket(
            symbol,
            direction,
            filled_qty,
            avg_px,
            stop_px,
            target_levels,
            trail_px,
            signal_meta,
            market_choice,
        )
        await self._place_bracket_orders(full_symbol, direction, filled_qty, stop_px, target_levels)

        self._set_coin_cooldown(symbol, now)
        self._arm_global_lock(now)

    # --------------------------------------------------------------------- helpers
    def _event_timestamp(self, evt: Dict[str, Any]) -> float:
        payload = evt.get("payload") or {}
        candidates = [
            evt.get("ts"),
            evt.get("timestamp"),
            evt.get("published"),
            payload.get("created_at"),
            payload.get("published_at"),
            payload.get("timestamp"),
        ]
        for candidate in candidates:
            try:
                value = float(candidate)
            except (TypeError, ValueError):
                continue
            if value > 10_000_000_000:
                value /= 1000.0
            if value > 0:
                return value
        return 0.0

    def _record_score(self, symbol: str, score: float) -> None:
        if not self.cfg.metrics_enabled or social_sentiment_signal_score is None:
            return
        try:
            social_sentiment_signal_score.labels(symbol=symbol).set(float(score))
        except Exception:
            pass

    def _contains_deny_term(self, text: str) -> bool:
        if not text or not self._deny_terms:
            return False
        text_low = text.lower()
        return any(term in text_low for term in self._deny_terms)

    def _event_text(self, evt: Dict[str, Any]) -> str:
        payload = evt.get("payload") or {}
        parts = [
            str(payload.get("text") or ""),
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            str(evt.get("headline") or ""),
        ]
        return " ".join(part for part in parts if part).lower()

    def _extract_author(self, evt: Dict[str, Any]) -> str:
        payload = evt.get("payload") or {}
        author = payload.get("author") or payload.get("user") or payload.get("account")
        if isinstance(author, dict):
            author = author.get("username") or author.get("screen_name") or author.get("handle")
        if isinstance(author, str):
            return author.lower().lstrip("@").strip()
        return ""

    def _resolve_direction(self, meta: _SignalMeta) -> Optional[str]:
        sentiment = meta.sentiment
        if sentiment >= float(self.cfg.min_sentiment):
            return "BUY"
        if sentiment <= float(self.cfg.negative_sentiment_threshold):
            return "SELL"
        confidence = meta.confidence
        if confidence >= 1.0 and sentiment > 0:
            return "BUY"
        if confidence >= 1.0 and sentiment < 0 and self.cfg.allow_shorts:
            return "SELL"
        return None

    def _score_event(self, evt: Dict[str, Any]) -> _SignalMeta:
        payload = evt.get("payload") or {}
        metrics = payload.get("metrics") or {}

        mentions = self._as_float(payload.get("mentions"))
        mentions = max(mentions, self._as_float(metrics.get("mention_count")))
        mentions = max(mentions, self._as_float(metrics.get("social_volume")))
        likes = self._as_float(metrics.get("like_count") or metrics.get("favorite_count"))
        retweets = self._as_float(metrics.get("retweet_count"))
        replies = self._as_float(metrics.get("reply_count") or metrics.get("comment_count"))
        quotes = self._as_float(metrics.get("quote_count"))

        engagement = mentions + (retweets * 1.5) + (likes * 0.4) + (replies * 0.6) + (quotes * 0.7)
        engagement = max(engagement, 0.0)

        velocity = self._as_float(payload.get("velocity"))
        velocity = max(velocity, self._as_float(metrics.get("velocity")))
        velocity = max(velocity, self._as_float(metrics.get("social_velocity")))
        velocity = max(velocity, 0.0)

        sentiment = self._as_float(payload.get("sentiment_score") or payload.get("sentiment"))
        sentiment = max(min(sentiment, 2.0), -2.0)

        price_change_pct = payload.get("price_change_pct")
        if price_change_pct is None:
            price_change_pct = payload.get("price_change_5m_pct")
        price_change_pct = self._normalize_pct(price_change_pct)

        confidence = self._as_float(evt.get("priority") or payload.get("confidence") or metrics.get("confidence") or 0.5)

        engagement_score = math.log1p(engagement)
        velocity_score = math.log1p(velocity)
        sentiment_score = max(sentiment, 0.0) * 0.6 if sentiment >= 0 else abs(sentiment) * 0.4
        price_score = math.log1p(max(price_change_pct, 0.0))

        score = (engagement_score * 0.4) + (velocity_score * 0.3) + (price_score * 0.15) + (confidence * 0.15)
        if sentiment > 0:
            score *= 1.0 + min(sentiment, 1.5) * 0.35
        elif sentiment < 0:
            score *= 1.0 + min(abs(sentiment), 1.5) * 0.2

        meta_payload = {
            "mentions": mentions,
            "likes": likes,
            "retweets": retweets,
            "replies": replies,
            "quotes": quotes,
        }

        return _SignalMeta(
            score=score,
            mentions=engagement,
            velocity=velocity,
            sentiment=sentiment,
            price_change=price_change_pct,
            confidence=confidence,
            engagement=engagement,
            raw_payload=meta_payload,
        )

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
        side: str,
        qty: float,
        avg_px: float,
        meta: _SignalMeta,
        market: str,
    ) -> None:
        topic = self.cfg.publish_topic
        if not topic:
            return
        payload = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "avg_price": avg_px,
            "score": meta.score,
            "mentions": meta.mentions,
            "velocity": meta.velocity,
            "sentiment": meta.sentiment,
            "price_change": meta.price_change,
            "confidence": meta.confidence,
            "market": market,
            "ts": int(self.clock.time() * 1000),
        }
        try:
            from engine.core.event_bus import BUS

            await BUS.publish(topic, payload)
        except Exception:
            pass

    async def _publish_bracket(
        self,
        symbol: str,
        side: str,
        qty: float,
        avg_px: float,
        stop_px: float,
        targets: Tuple[float, ...],
        trail_px: float,
        meta: _SignalMeta,
        market: str,
    ) -> None:
        try:
            from engine.core.event_bus import BUS

            await BUS.publish(
                "strategy.social_sentiment_bracket",
                {
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "avg_price": avg_px,
                    "stop_price": stop_px,
                    "targets": targets,
                    "trail_price": trail_px,
                    "score": meta.score,
                    "market": market,
                    "ts": int(self.clock.time() * 1000),
                },
            )
        except Exception:
            pass

    async def _place_bracket_orders(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_px: float,
        targets: Tuple[float, ...],
    ) -> None:
        try:
            exit_side = "SELL" if side == "BUY" else "BUY"
            if stop_px > 0 and qty > 0:
                await self.router.amend_stop_reduce_only(symbol, exit_side, stop_px, abs(qty))
            for target in targets:
                if target <= 0:
                    continue
                await self.router.place_reduce_only_limit(symbol, exit_side, abs(qty) / len(targets), target)
        except Exception:
            pass

    def _build_exit_levels(self, side: str, avg_px: float) -> Tuple[float, Tuple[float, ...], float]:
        if avg_px <= 0:
            return 0.0, tuple(), 0.0
        levels = self.cfg.take_profit_levels or (self.cfg.take_profit_pct,)
        if side == "BUY":
            stop = avg_px * max(0.0001, 1.0 - float(self.cfg.stop_loss_pct))
            targets = tuple(avg_px * (1.0 + float(level)) for level in levels)
            trail = avg_px * max(0.0001, 1.0 - float(self.cfg.trail_stop_pct))
        else:
            stop = avg_px * (1.0 + float(self.cfg.stop_loss_pct))
            targets = tuple(avg_px * (1.0 - float(level)) for level in levels)
            trail = avg_px * (1.0 + float(self.cfg.trail_stop_pct))
        return stop, targets, trail

    def _set_coin_cooldown(self, symbol: str, now: Optional[float] = None) -> None:
        cooldown = float(self.cfg.coin_cooldown_sec or self.cfg.cooldown_sec)
        if cooldown <= 0:
            return
        now = now or self.clock.time()
        until = now + cooldown
        self._coin_cooldowns[symbol] = until
        if self.cfg.metrics_enabled and social_sentiment_cooldown_epoch is not None:
            try:
                social_sentiment_cooldown_epoch.labels(symbol=symbol).set(until)
            except Exception:
                pass

    def _cooldown_active(self, symbol: str, now: float) -> bool:
        until = self._coin_cooldowns.get(symbol)
        if not until:
            return False
        if now >= until:
            self._coin_cooldowns.pop(symbol, None)
            return False
        return True

    def _arm_global_lock(self, now: float) -> None:
        lock = float(self.cfg.global_cooldown_sec)
        if lock <= 0:
            return
        self._global_lock_until = max(self._global_lock_until, now + lock)

    def _record_event(self, symbol: str, decision: str) -> None:
        if not self.cfg.metrics_enabled or social_sentiment_events_total is None:
            return
        try:
            social_sentiment_events_total.labels(symbol=symbol, decision=decision).inc()
        except Exception:
            pass

    def _record_order(self, symbol: str, status: str) -> None:
        if not self.cfg.metrics_enabled or social_sentiment_orders_total is None:
            return
        try:
            social_sentiment_orders_total.labels(symbol=symbol, status=status).inc()
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
        if len(base) > 10:
            return False
        return True

    def _extract_from_text(self, text: str) -> Iterable[str]:
        if not text:
            return []
        matches = re.findall(r"#([A-Za-z0-9_]{2,15})", text)
        results = [m.upper() for m in matches]
        if not results and "" not in text:
            for token in re.findall(r"\b([A-Za-z]{2,10})/USDT\b", text.upper()):
                results.append(f"{token}USDT")
        return results

    @staticmethod
    def _normalize_pct(value: Any) -> float:
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
    "SocialSentimentConfig",
    "SocialSentimentModule",
    "load_social_sentiment_config",
]
