from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from ..core.binance import BinanceREST
from ..metrics import strategy_universe_size
from .config import RuntimeConfig, UniverseFilterConfig

log = logging.getLogger("engine.runtime.universe")
_SUPPRESSIBLE_EXCEPTIONS = (
    OSError,
    ValueError,
    json.JSONDecodeError,
    httpx.HTTPError,
    RuntimeError,
    ConnectionError,
    asyncio.TimeoutError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    log.debug("%s suppressed: %s", context, exc, exc_info=True)


BINANCE_SPOT_STREAM = "wss://stream.binance.com:9443/stream?streams={streams}"


@dataclass(frozen=True)
class SymbolMetrics:
    symbol: str
    venue: str
    price: float
    volume_usdt: float
    open_interest_usd: float
    max_leverage: int
    bid_ask_spread_pct: float = 0.0
    atr_5m_pct: float = 0.0
    price_change_1h_pct: float = 0.0
    orderbook_depth_usd: float = 0.0
    bid_liquidity_usd: float = 0.0
    tick_size_pct: float = 0.0
    trend_30d_pct: float = 0.0
    listing_age_days: float | None = None
    news_score: float = 0.0
    news_flag: bool = False


class UniverseManager:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._universes: dict[str, tuple[int, tuple[str, ...]]] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._snapshot_dir = Path(config.snapshot_dir).expanduser() if config.snapshot_dir else None
        if self._snapshot_dir:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._spot_exchange_info: dict[str, dict] = {}
        self._futures_exchange_info: dict[str, dict] = {}

    async def update(
        self, strategy: str, symbols: Iterable[str], version_hint: int | None = None
    ) -> None:
        key = strategy.lower()
        async with self._lock:
            current_version, _ = self._universes.get(key, (0, ()))
            new_version = (current_version + 1) if version_hint is None else version_hint
            clean = tuple(dict.fromkeys(sym.upper() for sym in symbols))
            self._universes[key] = (new_version, clean)
            self._events.setdefault(key, asyncio.Event()).set()
            strategy_universe_size.labels(strategy=key).set(len(clean))
            if self._snapshot_dir:
                snapshot_path = self._snapshot_dir / f"{key}-{int(time.time())}.json"
                try:
                    with snapshot_path.open("w", encoding="utf-8") as fh:
                        json.dump(
                            {"strategy": key, "version": new_version, "symbols": clean},
                            fh,
                        )
                except (OSError, TypeError) as exc:
                    _log_suppressed("universe.snapshot_write", exc)

    async def current(self, strategy: str) -> tuple[int, tuple[str, ...]]:
        key = strategy.lower()
        async with self._lock:
            if key not in self._universes:
                default_symbols = tuple(sym.upper() for sym in self._config.symbols.core)
                self._universes[key] = (0, default_symbols)
            event = self._events.get(key)
            if event is None or event.is_set():
                self._events[key] = asyncio.Event()
            return self._universes[key]

    def metadata_snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._metadata)

    async def set_symbol_metadata(self, symbol: str, metadata: dict[str, Any]) -> None:
        async with self._lock:
            self._metadata[symbol.upper()] = dict(metadata)

    async def clear_symbol_metadata(self, symbol: str) -> None:
        async with self._lock:
            self._metadata.pop(symbol.upper(), None)

    async def wait_for_update(self, strategy: str, last_version: int) -> int:
        key = strategy.lower()
        while True:
            async with self._lock:
                current_version, _ = self._universes.get(key, (0, ()))
                if current_version != last_version:
                    return current_version
                event = self._events.setdefault(key, asyncio.Event())
            await event.wait()


class BinanceMetricsFetcher:
    def __init__(self, client: BinanceREST, timeout: float = 10.0) -> None:
        self.client = client
        self.timeout = timeout

    async def futures_ticker_24h(self) -> list[dict]:
        async with httpx.AsyncClient(
            base_url=self.client._futures_base,
            timeout=self.timeout,
            headers={"X-MBX-APIKEY": self.client._settings.api_key},
        ) as http:
            resp = await http.get("/fapi/v1/ticker/24hr")
            resp.raise_for_status()
            return resp.json()

    async def spot_ticker_24h(self) -> list[dict]:
        async with httpx.AsyncClient(
            base_url=self.client._spot_base,
            timeout=self.timeout,
            headers={"X-MBX-APIKEY": self.client._settings.api_key},
        ) as http:
            resp = await http.get("/api/v3/ticker/24hr")
            resp.raise_for_status()
            return resp.json()

    async def futures_open_interest(self, symbol: str) -> float:
        async with httpx.AsyncClient(
            base_url=self.client._futures_base,
            timeout=self.timeout,
            headers={"X-MBX-APIKEY": self.client._settings.api_key},
        ) as http:
            resp = await http.get("/fapi/v1/openInterest", params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("openInterest", 0.0))

    async def leverage_brackets(self) -> dict[str, int]:
        async with httpx.AsyncClient(
            base_url=self.client._futures_base,
            timeout=self.timeout,
            headers={"X-MBX-APIKEY": self.client._settings.api_key},
        ) as http:
            resp = await http.get("/fapi/v1/leverageBracket")
            resp.raise_for_status()
            brackets = resp.json()
            leverage: dict[str, int] = {}
            for entry in brackets or []:
                symbol = entry.get("symbol")
                if not symbol:
                    continue
                bracket = entry.get("brackets", [])
                if not bracket:
                    continue
                leverage[symbol.upper()] = int(bracket[0].get("initialLeverage", 1))
            return leverage


class UniverseScreener:
    def __init__(
        self, config: RuntimeConfig, client: BinanceREST, manager: UniverseManager
    ) -> None:
        self.config = config
        self.client = client
        self.manager = manager
        self.fetcher = BinanceMetricsFetcher(client)
        self._running = False
        self._task: asyncio.Task | None = None
        self._spot_exchange_info: dict[str, dict] = {}
        self._futures_exchange_info: dict[str, dict] = {}

    def start(self) -> None:
        if self._task:
            return
        loop = asyncio.get_running_loop()
        self._running = True
        self._task = loop.create_task(self._run(), name="universe-screener")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        refresh = max(60, int(self.config.scanner.refresh_seconds))
        while self._running:
            try:
                await self._refresh()
            except asyncio.CancelledError:
                raise
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                log.warning("universe refresh failed: %s", exc, exc_info=True)
            await asyncio.sleep(refresh)

    async def _refresh(self) -> None:
        await self._load_exchange_info()
        futures_metrics = await self._gather_futures_metrics()
        spot_metrics = await self._gather_spot_metrics()
        leverage = await self.fetcher.leverage_brackets()

        for sym, metric in list(futures_metrics.items()):
            futures_metrics[sym] = replace(
                metric, max_leverage=leverage.get(sym, metric.max_leverage)
            )

        metadata = self.manager.metadata_snapshot()
        universes = self.config.universes or {}
        for strategy, filter_cfg in universes.items():
            symbols = self._apply_filter(filter_cfg, futures_metrics, spot_metrics, metadata)
            await self.manager.update(strategy, symbols)
            log.info("[universe] strategy=%s symbols=%d", strategy, len(symbols))

    async def _load_exchange_info(self) -> None:
        if not self._spot_exchange_info:
            try:
                async with httpx.AsyncClient(
                    base_url=self.client._spot_base,
                    timeout=self.fetcher.timeout,
                ) as http:
                    resp = await http.get("/api/v3/exchangeInfo")
                    resp.raise_for_status()
                    data = resp.json()
                    info: dict[str, dict] = {}
                    for sym in data.get("symbols", []) or []:
                        symbol = str(sym.get("symbol") or "").upper()
                        if not symbol:
                            continue
                        filters = {f.get("filterType"): f for f in sym.get("filters", []) or []}
                        price_filter = filters.get("PRICE_FILTER", {})
                        tick_size = float(price_filter.get("tickSize", 0.0) or 0.0)
                        info[symbol] = {
                            "tickSize": tick_size,
                            "onboardDate": sym.get("onboardDate"),
                        }
                    if info:
                        self._spot_exchange_info = info
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("universe.spot_exchange_info", exc)

        if not self._futures_exchange_info:
            try:
                async with httpx.AsyncClient(
                    base_url=self.client._futures_base,
                    timeout=self.fetcher.timeout,
                    headers=(
                        {"X-MBX-APIKEY": self.client._settings.api_key}
                        if self.client._settings.api_key
                        else None
                    ),
                ) as http:
                    resp = await http.get("/fapi/v1/exchangeInfo")
                    resp.raise_for_status()
                    data = resp.json()
                    info: dict[str, dict] = {}
                    for sym in data.get("symbols", []) or []:
                        symbol = str(sym.get("symbol") or "").upper()
                        if not symbol:
                            continue
                        filters = {f.get("filterType"): f for f in sym.get("filters", []) or []}
                        price_filter = filters.get("PRICE_FILTER", {})
                        tick_size = float(price_filter.get("tickSize", 0.0) or 0.0)
                        info[symbol] = {
                            "tickSize": tick_size,
                            "onboardDate": sym.get("onboardDate"),
                        }
                    if info:
                        self._futures_exchange_info = info
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("universe.futures_exchange_info", exc)

    async def _gather_futures_metrics(self) -> dict[str, SymbolMetrics]:
        tickers = await self.fetcher.futures_ticker_24h()
        metrics: dict[str, SymbolMetrics] = {}
        for item in tickers:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol.endswith("USDT"):
                continue
            try:
                price = float(item.get("lastPrice") or 0.0)
                volume = float(item.get("quoteVolume") or 0.0)
            except (TypeError, ValueError):
                continue
            metrics[symbol] = SymbolMetrics(
                symbol=symbol,
                venue="futures",
                price=price,
                volume_usdt=volume,
                open_interest_usd=0.0,
                max_leverage=1,
            )
        # Fetch open interest for most liquid symbols only
        top_symbols = sorted(metrics.values(), key=lambda m: m.volume_usdt, reverse=True)[:200]
        semaphore = asyncio.Semaphore(10)

        async def fetch(symbol: str) -> None:
            async with semaphore:
                try:
                    oi = await self.fetcher.futures_open_interest(symbol)
                    metric = metrics.get(symbol)
                    if metric:
                        metrics[symbol] = SymbolMetrics(
                            symbol=metric.symbol,
                            venue=metric.venue,
                            price=metric.price,
                            volume_usdt=metric.volume_usdt,
                            open_interest_usd=oi * metric.price,
                            max_leverage=metric.max_leverage,
                        )
                except _SUPPRESSIBLE_EXCEPTIONS as exc:
                    _log_suppressed("universe.fetch_open_interest", exc)

        await asyncio.gather(*(fetch(m.symbol) for m in top_symbols))
        await self._enrich_metrics(metrics, venue="futures")
        return metrics

    async def _gather_spot_metrics(self) -> dict[str, SymbolMetrics]:
        tickers = await self.fetcher.spot_ticker_24h()
        metrics: dict[str, SymbolMetrics] = {}
        for item in tickers:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol.endswith("USDT"):
                continue
            try:
                price = float(item.get("lastPrice") or 0.0)
                volume = float(item.get("quoteVolume") or 0.0)
            except (TypeError, ValueError):
                continue
            metrics[symbol] = SymbolMetrics(
                symbol=symbol,
                venue="spot",
                price=price,
                volume_usdt=volume,
                open_interest_usd=0.0,
                max_leverage=0,
            )
        await self._enrich_metrics(metrics, venue="spot")
        return metrics

    async def _fetch_orderbook(
        self, symbol: str, venue: str, limit: int = 20
    ) -> tuple[float, float, float] | None:
        base_url = self.client._futures_base if venue == "futures" else self.client._spot_base
        path = "/fapi/v1/depth" if venue == "futures" else "/api/v3/depth"
        headers = (
            {"X-MBX-APIKEY": self.client._settings.api_key}
            if self.client._settings.api_key and venue == "futures"
            else None
        )
        try:
            async with httpx.AsyncClient(
                base_url=base_url, timeout=self.fetcher.timeout, headers=headers
            ) as http:
                resp = await http.get(path, params={"symbol": symbol, "limit": limit})
                resp.raise_for_status()
                data = resp.json()
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("universe.fetch_orderbook", exc)
            return None
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        if not bids or not asks:
            return None
        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
        except (TypeError, ValueError):
            return None
        bid_liq = 0.0
        ask_liq = 0.0
        for price_raw, qty_raw in bids:
            try:
                bid_liq += float(price_raw) * float(qty_raw)
            except (TypeError, ValueError):
                continue
        for price_raw, qty_raw in asks:
            try:
                ask_liq += float(price_raw) * float(qty_raw)
            except (TypeError, ValueError):
                continue
        mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else 0.0
        spread_pct = ((best_ask - best_bid) / mid * 100) if mid else 0.0
        depth = bid_liq + ask_liq
        return spread_pct, bid_liq, depth

    async def _fetch_klines(
        self, symbol: str, venue: str, interval: str, limit: int
    ) -> list[list[str]] | None:
        base_url = self.client._futures_base if venue == "futures" else self.client._spot_base
        path = "/fapi/v1/klines" if venue == "futures" else "/api/v3/klines"
        headers = (
            {"X-MBX-APIKEY": self.client._settings.api_key}
            if self.client._settings.api_key and venue == "futures"
            else None
        )
        try:
            async with httpx.AsyncClient(
                base_url=base_url, timeout=self.fetcher.timeout, headers=headers
            ) as http:
                resp = await http.get(
                    path,
                    params={"symbol": symbol, "interval": interval, "limit": limit},
                )
                resp.raise_for_status()
                return resp.json()
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("universe.fetch_klines", exc)
            return None

    async def _enrich_metrics(self, metrics: dict[str, SymbolMetrics], venue: str) -> None:
        if not metrics:
            return
        info_map = self._futures_exchange_info if venue == "futures" else self._spot_exchange_info
        ordered = sorted(metrics.values(), key=lambda m: m.volume_usdt, reverse=True)
        limit = min(len(ordered), 80)
        semaphore = asyncio.Semaphore(6)

        async def enrich(metric: SymbolMetrics) -> None:
            async with semaphore:
                spread_pct = 0.0
                bid_liq = 0.0
                depth = 0.0
                orderbook = await self._fetch_orderbook(metric.symbol, venue)
                if orderbook:
                    spread_pct, bid_liq, depth = orderbook

                atr_pct = 0.0
                price_change_pct = 0.0
                klines_5m = await self._fetch_klines(metric.symbol, venue, "5m", 60)
                if klines_5m:
                    atr_pct = self._compute_atr_pct(klines_5m)
                    price_change_pct = self._compute_price_change_pct(klines_5m, steps=12)

                trend_pct = 0.0
                klines_1d = await self._fetch_klines(metric.symbol, venue, "1d", 31)
                if klines_1d:
                    trend_pct = self._compute_trend_pct(klines_1d)

                tick_size = 0.0
                listing_age = None
                info = info_map.get(metric.symbol, {})
                try:
                    tick_size = float(info.get("tickSize", 0.0) or 0.0)
                except (TypeError, ValueError):
                    tick_size = 0.0
                onboard = info.get("onboardDate")
                if onboard not in (None, ""):
                    try:
                        age_days = (time.time() * 1000 - float(onboard)) / 86_400_000.0
                        listing_age = max(0.0, age_days)
                    except (TypeError, ValueError):
                        listing_age = None

                tick_pct = (
                    (tick_size / metric.price * 100.0)
                    if metric.price > 0 and tick_size > 0
                    else 0.0
                )

                metrics[metric.symbol] = replace(
                    metric,
                    bid_ask_spread_pct=spread_pct,
                    atr_5m_pct=atr_pct,
                    price_change_1h_pct=price_change_pct,
                    orderbook_depth_usd=depth,
                    bid_liquidity_usd=bid_liq,
                    tick_size_pct=tick_pct,
                    trend_30d_pct=trend_pct,
                    listing_age_days=listing_age,
                )

        await asyncio.gather(*(enrich(metric) for metric in ordered[:limit]))

    @staticmethod
    def _compute_atr_pct(klines: list[list[str]], period: int = 14) -> float:
        if not klines or len(klines) <= period:
            return 0.0
        trs: list[float] = []
        prev_close = float(klines[0][4])
        for row in klines[1:]:
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        if not trs:
            return 0.0
        recent = trs[-period:]
        atr = sum(recent) / len(recent)
        last_close = float(klines[-1][4])
        return (atr / last_close) * 100 if last_close else 0.0

    @staticmethod
    def _compute_price_change_pct(klines: list[list[str]], steps: int) -> float:
        closes = [float(row[4]) for row in klines if float(row[4]) > 0]
        if len(closes) <= steps:
            return 0.0
        last = closes[-1]
        base = closes[-steps - 1]
        return ((last / base) - 1.0) * 100 if base else 0.0

    @staticmethod
    def _compute_trend_pct(klines: list[list[str]]) -> float:
        closes = [float(row[4]) for row in klines if float(row[4]) > 0]
        if len(closes) < 2:
            return 0.0
        first = closes[0]
        last = closes[-1]
        return ((last / first) - 1.0) * 100 if first else 0.0

    @staticmethod
    def _apply_filter(
        filter_cfg: UniverseFilterConfig,
        futures_metrics: dict[str, SymbolMetrics],
        spot_metrics: dict[str, SymbolMetrics],
        metadata: dict[str, dict[str, Any]],
    ) -> list[str]:
        venues = set(filter_cfg.venues or ["futures"])
        candidates: list[SymbolMetrics] = []
        include_set = {sym.upper() for sym in filter_cfg.include_symbols}
        metadata = {k.upper(): v for k, v in (metadata or {}).items()}

        def passes(metric: SymbolMetrics) -> bool:
            symbol = metric.symbol.upper()
            meta = metadata.get(symbol, {})
            if symbol in include_set:
                return True
            if metric.volume_usdt < filter_cfg.min_24h_volume_usdt:
                return False
            if metric.price < filter_cfg.min_price_usdt:
                return False
            if filter_cfg.max_price_usdt is not None and metric.price > filter_cfg.max_price_usdt:
                return False
            if metric.venue == "futures" and filter_cfg.min_futures_open_interest_usdt is not None:
                if metric.open_interest_usd < filter_cfg.min_futures_open_interest_usdt:
                    return False
            if metric.venue == "futures" and filter_cfg.min_leverage_supported is not None:
                if metric.max_leverage < filter_cfg.min_leverage_supported:
                    return False
            if (
                filter_cfg.min_30d_trend_pct is not None
                and metric.trend_30d_pct < filter_cfg.min_30d_trend_pct
            ):
                return False
            if (
                filter_cfg.max_bid_ask_spread_pct is not None
                and metric.bid_ask_spread_pct > filter_cfg.max_bid_ask_spread_pct
            ):
                return False
            if (
                filter_cfg.min_5m_atr_pct is not None
                and metric.atr_5m_pct < filter_cfg.min_5m_atr_pct
            ):
                return False
            if (
                filter_cfg.min_price_change_pct_last_1h is not None
                and metric.price_change_1h_pct < filter_cfg.min_price_change_pct_last_1h
            ):
                return False
            if (
                filter_cfg.min_liquidity_bid_size is not None
                and metric.bid_liquidity_usd < filter_cfg.min_liquidity_bid_size
            ):
                return False
            if (
                filter_cfg.min_orderbook_depth_usdt is not None
                and metric.orderbook_depth_usd < filter_cfg.min_orderbook_depth_usdt
            ):
                return False
            if (
                filter_cfg.min_tick_size_pct is not None
                and metric.tick_size_pct < filter_cfg.min_tick_size_pct
            ):
                return False
            if filter_cfg.new_listing_within_days is not None:
                if metric.listing_age_days is None or metric.listing_age_days > float(
                    filter_cfg.new_listing_within_days
                ):
                    return False
            if filter_cfg.has_major_news_flag and not bool(
                meta.get("has_major_news_flag") or meta.get("news_flag")
            ):
                return False
            upper_symbol = symbol
            for prefix in filter_cfg.exclude_prefixes:
                if upper_symbol.startswith(prefix.upper()):
                    return False
            for suffix in filter_cfg.exclude_suffixes:
                if upper_symbol.endswith(suffix.upper()):
                    return False
            for token in filter_cfg.exclude_contains:
                if token.upper() in upper_symbol:
                    return False
            return True

        if "futures" in venues:
            for metric in futures_metrics.values():
                if passes(metric):
                    candidates.append(metric)
        if "spot" in venues:
            for metric in spot_metrics.values():
                if passes(metric):
                    candidates.append(metric)

        for sym in include_set:
            if sym not in {m.symbol for m in candidates}:
                metric = futures_metrics.get(sym) or spot_metrics.get(sym)
                if metric:
                    candidates.append(metric)

        def metric_value(metric: SymbolMetrics, key: str) -> float:
            sym_meta = metadata.get(metric.symbol.upper(), {})
            key = key.lower()
            if key in {"24h_volume_usdt", "volume_usdt"}:
                return metric.volume_usdt
            if key in {"futures_open_interest_usdt", "open_interest_usd"}:
                return metric.open_interest_usd
            if key in {"price", "last_price"}:
                return metric.price
            if key == "price_change_pct_last_1h":
                return metric.price_change_1h_pct
            if key == "5m_atr_pct":
                return metric.atr_5m_pct
            if key in {"orderbook_depth_usdt", "depth_usdt"}:
                return metric.orderbook_depth_usd
            if key in {"bid_liquidity_usd", "liquidity_bid"}:
                return metric.bid_liquidity_usd
            if key == "news_score":
                return float(sym_meta.get("news_score", 0.0) or 0.0)
            if key == "trend_30d_pct":
                return metric.trend_30d_pct
            return 0.0

        if filter_cfg.sort_by:
            candidates.sort(
                key=lambda m: tuple(metric_value(m, sort_key) for sort_key in filter_cfg.sort_by),
                reverse=True,
            )

        seen: set[str] = set()
        ordered: list[str] = []
        for metric in candidates:
            sym = metric.symbol.upper()
            if sym in seen:
                continue
            seen.add(sym)
            ordered.append(sym)

        limit = filter_cfg.max_symbols
        if filter_cfg.max_concurrent_symbols is not None:
            limit = min(
                limit or filter_cfg.max_concurrent_symbols,
                filter_cfg.max_concurrent_symbols,
            )
        if limit is not None:
            ordered = ordered[:limit]

        return ordered
