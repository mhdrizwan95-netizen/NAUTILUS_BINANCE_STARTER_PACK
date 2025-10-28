from __future__ import annotations

"""
External data feed connectors.

These classes normalize upstream signals (social, listings, macro, on-chain)
into the shared event schema documented in
`docs/Comprehensive Framework for a Binance Crypto Trading Bot.md`.

Each connector is intentionally stubbed – it wires metrics, config plumbing,
and event shaping so we can drop in real API integrations later without
rewriting the orchestration glue.
"""

import asyncio
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import httpx
import yaml

from engine.core.signal_queue import SIGNAL_QUEUE, QueuedEvent
from engine.metrics import (
    external_feed_events_total,
    external_feed_errors_total,
    external_feed_latency_seconds,
    external_feed_last_event_epoch,
)

logger = logging.getLogger(__name__)

EXTERNAL_EVENT_TOPIC = "events.external_feed"
DEFAULT_CONFIG_PATH = Path(os.getenv("EXTERNAL_FEEDS_CONFIG", "config/external_feeds.yaml"))


@dataclass
class ExternalFeedEvent:
    """Normalized event payload handed to the signal bus."""

    source: str
    payload: Dict[str, Any]
    asset_hints: List[str] = field(default_factory=list)
    priority: float = 0.5
    expires_at: Optional[float] = None

    def asdict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "payload": self.payload,
            "asset_hints": self.asset_hints,
            "priority": float(self.priority),
            "expires_at": self.expires_at,
        }


class ExternalFeedConnector:
    """
    Base class for feed connectors.

    Sub-classes implement `collect()` to return ExternalFeedEvent instances.
    """

    topic = EXTERNAL_EVENT_TOPIC

    def __init__(
        self,
        source: str,
        *,
        poll_interval: float = 30.0,
        default_priority: float = 0.5,
        config: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> None:
        self.source = source
        self.poll_interval = max(float(poll_interval), 1.0)
        self.default_priority = float(default_priority)
        self.config = config or {}
        self.timeout = float(self.config.get("timeout_sec", timeout))
        self._log = logging.getLogger(f"engine.feeds.external.{source}")
        self._running = True
        self._http_client: httpx.AsyncClient | None = None

    def build_event(
        self,
        payload: Dict[str, Any],
        *,
        asset_hints: Optional[Iterable[str]] = None,
        priority: Optional[float] = None,
        ttl_sec: Optional[float] = None,
    ) -> ExternalFeedEvent:
        expires_at = time.time() + float(ttl_sec) if ttl_sec else None
        hints = [h.upper() for h in (asset_hints or [])]
        return ExternalFeedEvent(
            source=self.source,
            payload=payload,
            asset_hints=hints,
            priority=priority if priority is not None else self.default_priority,
            expires_at=expires_at,
        )

    async def collect(self) -> List[ExternalFeedEvent]:
        """
        Override in sub-classes.

        Should return a list of ExternalFeedEvent objects (may be empty).
        """
        return []

    async def run(self) -> None:
        """Start the polling loop."""
        self._log.info("External feed '%s' online (poll=%ss)", self.source, self.poll_interval)
        while self._running:
            started = time.perf_counter()
            try:
                events = await self.collect()
                latency = time.perf_counter() - started
                external_feed_latency_seconds.labels(self.source).observe(latency)
                published = 0
                for event in events or []:
                    payload = event.asdict()
                    await SIGNAL_QUEUE.put(
                        QueuedEvent(
                            topic=self.topic,
                            data=payload,
                            priority=payload.get("priority", self.default_priority),
                            expires_at=payload.get("expires_at"),
                            source=self.source,
                        )
                    )
                    external_feed_events_total.labels(self.source).inc()
                    external_feed_last_event_epoch.labels(self.source).set(time.time())
                    published += 1
                if published:
                    self._log.debug("Published %d event(s) for %s", published, self.source)
            except asyncio.CancelledError:
                self._log.info("External feed '%s' cancelled", self.source)
                break
            except Exception as exc:
                external_feed_errors_total.labels(self.source).inc()
                self._log.warning("External feed '%s' failed: %s", self.source, exc, exc_info=True)
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False


class _SeededConnectorMixin:
    """Utility mixin that emits events defined in config.seed_events."""

    def __init__(self, *_, config: Optional[Dict[str, Any]] = None, **__) -> None:
        cfg = config or {}
        seeds = cfg.get("seed_events") or []
        self._seed_events = deque(seeds)
        super().__init__(*_, config=cfg, **__)

    def _drain_seed(self) -> Optional[ExternalFeedEvent]:
        if not self._seed_events:
            return None
        raw = self._seed_events.popleft() or {}
        payload = raw.get("payload") or {k: v for k, v in raw.items() if k not in {"asset_hints", "priority", "ttl_sec"}}
        asset_hints = raw.get("asset_hints") or []
        priority = raw.get("priority")
        ttl_sec = raw.get("ttl_sec")
        return self.build_event(payload, asset_hints=asset_hints, priority=priority, ttl_sec=ttl_sec)


class TwitterFirehoseConnector(_SeededConnectorMixin, ExternalFeedConnector):
    """Fetch recent tweets via Twitter/X recent search API."""

    def __init__(self, source: str, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        poll = cfg.get("poll_interval", 5.0)
        priority = cfg.get("priority", 0.9)
        super().__init__(source, poll_interval=poll, default_priority=priority, config=cfg)
        self.bearer_token = str(cfg.get("bearer_token") or "").strip()
        self.query = cfg.get("query")
        keywords = cfg.get("keywords")
        if not self.query and keywords:
            joined = " OR ".join(keywords)
            self.query = f"({joined}) lang:en"
        self.expansions = cfg.get("expansions") or []
        self.max_results = int(cfg.get("max_results", 25))
        self.asset_keyword_map: Dict[str, List[str]] = {
            str(k).lower(): v for k, v in (cfg.get("asset_keyword_map") or {}).items()
        }
        self.ttl_sec = float(cfg.get("ttl_sec", 900))
        self._since_id: Optional[str] = None
        self._warned_token = False

    async def collect(self) -> List[ExternalFeedEvent]:
        if not self.bearer_token:
            if not self._warned_token:
                self._log.warning("Bearer token missing for twitter feed '%s'; skipping", self.source)
                self._warned_token = True
            return []
        event = self._drain_seed()
        events: List[ExternalFeedEvent] = [event] if event else []
        params = {
            "query": self.query or "(bitcoin OR eth OR doge) lang:en",
            "max_results": max(min(self.max_results, 100), 10),
            "tweet.fields": "created_at,lang,author_id,public_metrics",
        }
        if self.expansions:
            params["expansions"] = ",".join(self.expansions)
        if self._since_id:
            params["since_id"] = self._since_id

        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        url = "https://api.twitter.com/2/tweets/search/recent"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 429:
                    self._log.warning("Twitter rate limited for %s, backing off", self.source)
                    return events
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as exc:
            external_feed_errors_total.labels(self.source).inc()
            self._log.warning("Twitter fetch failed: %s", exc)
            return events

        results = data.get("data") or []
        meta = data.get("meta") or {}
        if "newest_id" in meta:
            self._since_id = meta["newest_id"]

        for tweet in results:
            tid = tweet.get("id")
            text = (tweet.get("text") or "").strip()
            if not text:
                continue
            asset_hints = self._extract_assets(text)
            payload = {
                "id": tid,
                "text": text,
                "author_id": tweet.get("author_id"),
                "created_at": tweet.get("created_at"),
                "lang": tweet.get("lang"),
                "metrics": tweet.get("public_metrics"),
                "url": f"https://twitter.com/i/web/status/{tid}",
            }
            events.append(
                self.build_event(
                    payload,
                    asset_hints=asset_hints,
                    priority=self.default_priority,
                    ttl_sec=self.ttl_sec,
                )
            )
        return events

    def _extract_assets(self, text: str) -> List[str]:
        asset_hints: List[str] = []
        lowered = text.lower()
        for key, assets in self.asset_keyword_map.items():
            if key in lowered:
                asset_hints.extend(assets)
        # Hashtag-based fallback
        for match in re.findall(r"#([A-Za-z0-9_]{2,15})", text):
            sym = match.upper()
            if sym.endswith("USDT"):
                asset_hints.append(sym)
            elif len(sym) <= 5:
                asset_hints.append(sym)
        return list(dict.fromkeys(asset_hints))


class BinanceListingConnector(_SeededConnectorMixin, ExternalFeedConnector):
    """Poll Binance announcement API for new listings."""

    PROMO_KEYWORDS = (
        "promotion",
        "promo",
        "airdrop",
        "launchpool",
        "launchpad",
        "reward",
        "voucher",
        "campaign",
        "bonus",
        "rebate",
    )

    def __init__(self, source: str, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        poll = cfg.get("poll_interval", 45.0)
        priority = cfg.get("priority", 0.88)
        super().__init__(source, poll_interval=poll, default_priority=priority, config=cfg)
        self.languages = cfg.get("languages") or ["en"]
        self.url = cfg.get("rss_url") or "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageSize=20"
        self.asset_suffixes = cfg.get("asset_suffixes") or ["USDT"]
        self.ttl_sec = float(cfg.get("ttl_sec", 1800))
        self._seen_ids: Set[str] = set()

    def _first_nonempty_text(self, article: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
        for key in keys:
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_campaign_tags(self, *texts: Optional[str]) -> List[str]:
        hits: Set[str] = set()
        for text in texts:
            if not text:
                continue
            lowered = text.lower()
            for keyword in self.PROMO_KEYWORDS:
                if keyword in lowered:
                    hits.add(keyword)
        return sorted(hits)

    def _extract_article_tags(self, article: Dict[str, Any]) -> List[str]:
        raw_tags: List[str] = []
        for key in ("tags", "relatedTags", "categories", "category", "topics"):
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                raw_tags.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        raw_tags.append(item.strip())
                    elif isinstance(item, dict):
                        name = item.get("name") or item.get("title")
                        if isinstance(name, str) and name.strip():
                            raw_tags.append(name.strip())
        return list(dict.fromkeys(raw_tags))

    def _find_tickers_in_text(self, text: Optional[str]) -> List[str]:
        if not text:
            return []
        candidates = re.findall(r"\b[A-Z0-9]{3,10}\b", text)
        tickers: List[str] = []
        for cand in candidates:
            sym = cand.upper()
            if sym.endswith(tuple(self.asset_suffixes)):
                tickers.append(sym)
            elif 3 <= len(sym) <= 6 and sym.isalpha():
                for suffix in self.asset_suffixes:
                    tickers.append(f"{sym}{suffix}")
        return tickers

    async def collect(self) -> List[ExternalFeedEvent]:
        events: List[ExternalFeedEvent] = []
        seed = self._drain_seed()
        if seed:
            events.append(seed)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.url)
                resp.raise_for_status()
                payload = resp.json() or {}
        except Exception as exc:
            external_feed_errors_total.labels(self.source).inc()
            self._log.warning("Binance announcement fetch failed: %s", exc)
            return events

        articles = self._extract_articles(payload)
        for article in articles:
            article_id = str(article.get("id") or article.get("articleId") or "")
            if not article_id or article_id in self._seen_ids:
                continue
            title = str(article.get("title") or article.get("titleText") or "")
            if not title:
                continue
            if "will list" not in title.lower():
                continue
            tickers = self._extract_tickers(article, title)
            summary = self._first_nonempty_text(
                article,
                (
                    "summary",
                    "brief",
                    "description",
                    "seoDescription",
                    "subtitle",
                    "digest",
                    "intro",
                ),
            )
            content = self._first_nonempty_text(
                article,
                (
                    "content",
                    "body",
                    "articleContent",
                    "richText",
                    "articleContentEn",
                    "text",
                ),
            )
            tickers.extend(self._find_tickers_in_text(summary))
            tickers.extend(self._find_tickers_in_text(content))
            tickers = list(dict.fromkeys(tickers))
            published = article.get("publishTime") or article.get("releaseDate")
            self._seen_ids.add(article_id)
            asset_hints = []
            for sym in tickers:
                if sym.endswith(tuple(self.asset_suffixes)):
                    asset_hints.append(sym)
                else:
                    for suffix in self.asset_suffixes:
                        asset_hints.append(f"{sym}{suffix}")
            article_tags = self._extract_article_tags(article)
            campaign_tags = self._extract_campaign_tags(title, summary, content)
            language = article.get("language") or article.get("lang")
            payload: Dict[str, Any] = {
                "id": article_id,
                "title": title,
                "tickers": tickers,
                "url": article.get("url") or article.get("linkUrl"),
                "published": published,
            }
            if summary:
                payload["summary"] = summary
            if content:
                payload["content"] = content
            if language:
                payload["language"] = str(language)
            if article_tags:
                payload["article_tags"] = article_tags
            if campaign_tags:
                payload["campaign_tags"] = campaign_tags
                payload["matched_keywords"] = campaign_tags
            if article.get("type"):
                payload["category"] = article.get("type")
            if article.get("code"):
                payload["article_code"] = article.get("code")
            if article.get("sourceName"):
                payload["source_name"] = article.get("sourceName")

            events.append(
                self.build_event(
                    payload,
                    asset_hints=list(dict.fromkeys(asset_hints)),
                    priority=self.default_priority,
                    ttl_sec=self.ttl_sec,
                )
            )
        # Keep seen set bounded
        if len(self._seen_ids) > 500:
            self._seen_ids = set(list(self._seen_ids)[-200:])
        return events

    def _extract_articles(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = payload.get("data")
        articles: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    articles.append(item)
        elif isinstance(data, dict):
            if "catalogs" in data:
                for catalog in data["catalogs"] or []:
                    articles.extend(catalog.get("articles") or [])
            if "articles" in data:
                articles.extend(data.get("articles") or [])
        return articles

    def _extract_tickers(self, article: Dict[str, Any], title: str) -> List[str]:
        tickers = []
        candidates = []
        if "symbols" in article:
            candidates.extend(article.get("symbols") or [])
        if "relatedCoins" in article:
            for coin in article.get("relatedCoins") or []:
                symbol = coin.get("coin")
                if symbol:
                    candidates.append(symbol)
        if not candidates:
            candidates = re.findall(r"\b[A-Z0-9]{3,8}\b", title)
        for cand in candidates:
            sym = str(cand).upper()
            tickers.append(sym)
        return list(dict.fromkeys(tickers))


class DexWhaleConnector(_SeededConnectorMixin, ExternalFeedConnector):
    """Fetch trending DEX pairs and emit events for high-velocity movers."""

    def __init__(self, source: str, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        poll = cfg.get("poll_interval", 15.0)
        priority = cfg.get("priority", 0.7)
        self.min_liquidity = cfg.get("min_liquidity_usd", 200_000)
        self.min_volume = cfg.get("min_volume_usd", 400_000)
        self.chains = cfg.get("chains") or ["eth", "bsc", "base"]
        self.change_threshold = float(cfg.get("change_m5_threshold", 6.0))
        self.api_url = cfg.get("dex_api") or "https://api.dexscreener.com/latest/dex/search?q=trending"
        self.ttl_sec = float(cfg.get("ttl_sec", 600))
        super().__init__(source, poll_interval=poll, default_priority=priority, config=cfg)
        self._seen_pairs: Set[str] = set()

    async def collect(self) -> List[ExternalFeedEvent]:
        events: List[ExternalFeedEvent] = []
        seed = self._drain_seed()
        if seed:
            events.append(seed)
        params = {"chains": ",".join(self.chains)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.api_url, params=params)
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as exc:
            external_feed_errors_total.labels(self.source).inc()
            self._log.warning("Dex connector fetch failed: %s", exc)
            return events

        pairs = self._extract_pairs(data)
        now = time.time()
        for item in pairs:
            addr = str(item.get("pairAddress") or item.get("address") or item.get("id") or "")
            chain = str(item.get("chainId") or item.get("chain") or "?")
            key = f"{chain}:{addr}"
            if not addr or key in self._seen_pairs:
                continue
            liquidity = self._as_float(self._nested(item, ("liquidity", "usd")))
            vol_24h = self._as_float(self._nested(item, ("volume", "h24")))
            vol_1h = self._as_float(self._nested(item, ("volume", "h1")))
            change_5m = self._as_float(self._nested(item, ("priceChange", "m5")) or item.get("change5m"))
            if liquidity < self.min_liquidity or vol_24h < self.min_volume:
                continue
            if change_5m < self.change_threshold:
                continue
            self._seen_pairs.add(key)
            base = item.get("baseToken") or {}
            symbol = str(base.get("symbol") or item.get("symbol") or "?").upper()
            payload = {
                "pair": key,
                "symbol": symbol,
                "name": base.get("name") or item.get("name"),
                "chain": chain,
                "price_usd": self._as_float(item.get("priceUsd") or item.get("price")),
                "liquidity_usd": liquidity,
                "volume_1h": vol_1h,
                "volume_24h": vol_24h,
                "change_5m": change_5m,
                "dex_url": item.get("url") or item.get("txns", {}).get("h24"),
                "updated": now,
            }
            events.append(
                self.build_event(
                    payload,
                    asset_hints=[symbol],
                    priority=self.default_priority,
                    ttl_sec=self.ttl_sec,
                )
            )
        # bound seen pairs
        if len(self._seen_pairs) > 500:
            self._seen_pairs = set(list(self._seen_pairs)[-200:])
        return events

    def _extract_pairs(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if "pairs" in data and isinstance(data["pairs"], list):
            return data["pairs"]
        if "tokens" in data and isinstance(data["tokens"], list):
            return data["tokens"]
        return []

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _nested(data: Dict[str, Any], path: Iterable[str]) -> Any:
        cur = data
        for part in path:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur


class MacroCalendarConnector(_SeededConnectorMixin, ExternalFeedConnector):
    """Consume an ICS calendar of macro events."""

    def __init__(self, source: str, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        poll = cfg.get("poll_interval", 1800.0)
        priority = cfg.get("priority", 0.4)
        super().__init__(source, poll_interval=poll, default_priority=priority, config=cfg)
        self.lookahead_hours = float(cfg.get("lookahead_hours", 72))
        self.ics_url = cfg.get("ics_url")
        self.include_keywords = [kw.lower() for kw in (cfg.get("include_keywords") or [])]
        self.ttl_sec = float(cfg.get("ttl_sec", 86400))
        self._seen_events: Set[str] = set()

    async def collect(self) -> List[ExternalFeedEvent]:
        events: List[ExternalFeedEvent] = []
        seed = self._drain_seed()
        if seed:
            events.append(seed)
        if not self.ics_url:
            return events
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.ics_url)
                resp.raise_for_status()
                text = resp.text
        except Exception as exc:
            external_feed_errors_total.labels(self.source).inc()
            self._log.warning("Macro calendar fetch failed: %s", exc)
            return events

        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=self.lookahead_hours)
        for event in self._parse_ics(text):
            uid = event.get("uid")
            title = event.get("summary") or ""
            start = event.get("dtstart")
            if not uid or uid in self._seen_events or not start:
                continue
            if start < now or start > horizon:
                continue
            if self.include_keywords and not any(kw in title.lower() for kw in self.include_keywords):
                continue
            self._seen_events.add(uid)
            events.append(
                self.build_event(
                    {
                        "uid": uid,
                        "title": title,
                        "start": start.isoformat(),
                        "description": event.get("description"),
                        "location": event.get("location"),
                    },
                    asset_hints=["BTCUSDT", "ETHUSDT"],
                    priority=self.default_priority,
                    ttl_sec=self.ttl_sec,
                )
            )
        if len(self._seen_events) > 500:
            self._seen_events = set(list(self._seen_events)[-200:])
        return events

    def _parse_ics(self, text: str) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        blocks = text.split("BEGIN:VEVENT")
        for block in blocks[1:]:
            lines = block.splitlines()
            event: Dict[str, Any] = {}
            for raw_line in lines:
                line = raw_line.strip()
                if line.startswith("UID:"):
                    event["uid"] = line[4:]
                elif line.startswith("SUMMARY:"):
                    event["summary"] = line[8:]
                elif line.startswith("DESCRIPTION:"):
                    event["description"] = line[12:]
                elif line.startswith("LOCATION:"):
                    event["location"] = line[9:]
                elif line.startswith("DTSTART"):
                    value = line.split(":", 1)[-1]
                    event["dtstart"] = self._parse_dt(value)
                elif line.startswith("END:VEVENT"):
                    break
            if "uid" in event:
                events.append(event)
        return events

    @staticmethod
    def _parse_dt(value: str) -> Optional[datetime]:
        value = value.strip()
        for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
            try:
                dt = datetime.strptime(value, fmt)
                if fmt.endswith("Z"):
                    return dt.replace(tzinfo=timezone.utc)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None


CONNECTOR_TYPES = {
    "twitter": TwitterFirehoseConnector,
    "twitter_firehose": TwitterFirehoseConnector,
    "binance_announcements": BinanceListingConnector,
    "binance_listings": BinanceListingConnector,
    "dex_whale": DexWhaleConnector,
    "dex_screener": DexWhaleConnector,
    "macro": MacroCalendarConnector,
    "macro_calendar": MacroCalendarConnector,
}


def load_feed_config(path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Load YAML config describing external feed connectors."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        logger.info("External feed config not found at %s", cfg_path)
        return {}
    data = yaml.safe_load(cfg_path.read_text()) or {}
    return data.get("feeds") or {}


def build_connectors(feeds_cfg: Dict[str, Any]) -> List[ExternalFeedConnector]:
    connectors: List[ExternalFeedConnector] = []
    for name, cfg in feeds_cfg.items():
        if not isinstance(cfg, dict):
            logger.warning("Feed config for %s must be a mapping", name)
            continue
        if not cfg.get("enabled", True):
            continue
        feed_type = (cfg.get("type") or name).lower()
        cls = CONNECTOR_TYPES.get(feed_type)
        if not cls:
            logger.warning("No connector registered for type '%s' (feed=%s)", feed_type, name)
            continue
        instance = cls(source=cfg.get("source") or name, config=cfg)
        connectors.append(instance)
    return connectors


async def spawn_external_feeds_from_config(path: Optional[Path | str] = None) -> List[str]:
    """
    Build connectors from config and start their run loops.

    Returns a list of connector source names that were scheduled.
    """
    feeds_cfg = load_feed_config(path)
    connectors = build_connectors(feeds_cfg)
    if not connectors:
        return []
    started: List[str] = []
    loop = asyncio.get_running_loop()
    for connector in connectors:
        loop.create_task(connector.run(), name=f"external-feed-{connector.source}")
        started.append(connector.source)
    return started
