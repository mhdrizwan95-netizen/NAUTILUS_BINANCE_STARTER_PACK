from __future__ import annotations

import argparse
import asyncio
import random
import string
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from engine.runtime.config import load_runtime_config, RuntimeConfig
from engine.runtime.pipeline import StrategyPipeline, Signal, StrategyRegistry
from engine.runtime.universe import UniverseManager, UniverseScreener, SymbolMetrics
from engine.core.order_router import OrderRouter
from engine.core.portfolio import Portfolio


def _random_symbol(prefix: str, i: int) -> str:
    suffix = ''.join(random.choices(string.ascii_uppercase, k=2))
    return f"{prefix}{i:03d}{suffix}USDT"


class DummyClient:
    def __init__(self, *, mismatched: Optional[Set[str]] = None) -> None:
        self._symbol_leverage: Dict[str, int] = {}
        self._mismatched = {sym.upper() for sym in (mismatched or set())}

    async def submit_market_quote(self, symbol: str, side: str, quote: float, market: Optional[str] = None):
        await asyncio.sleep(random.uniform(0.0, 0.02))
        price = 100.0 * (1 + random.uniform(-0.01, 0.01))
        qty = quote / price if price else quote / 100.0
        return {
            "filled_qty_base": qty,
            "avg_fill_price": price,
            "executedQty": qty,
            "price": price,
        }

    async def submit_limit_order(self, symbol: str, side: str, quantity: float, price: float, **_kwargs):
        await asyncio.sleep(random.uniform(0, 0.01))
        return {"orderId": random.randint(1, 1_000_000), "status": "NEW"}

    async def amend_reduce_only_stop(self, *args, **kwargs):  # noqa: ANN001
        await asyncio.sleep(random.uniform(0, 0.005))
        return {}

    async def place_reduce_only_limit(self, *args, **kwargs):  # noqa: ANN001
        await asyncio.sleep(random.uniform(0, 0.005))
        return {}

    async def futures_change_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        await asyncio.sleep(random.uniform(0.0, 0.01))
        sym = symbol.upper()
        if sym in self._mismatched:
            applied = leverage + 1
        else:
            applied = leverage
        self._symbol_leverage[sym] = applied
        return {"symbol": sym, "leverage": applied}

    async def position_risk(self, *, market: Optional[str] = None) -> List[Dict[str, Any]]:
        await asyncio.sleep(random.uniform(0.0, 0.005))
        return [
            {"symbol": sym, "leverage": lev, "positionAmt": 0, "entryPrice": 0}
            for sym, lev in self._symbol_leverage.items()
        ]


@dataclass
class SyntheticExchange:
    symbols: List[str]
    base_price: float = 100.0
    spike_chance: float = 0.02

    def __post_init__(self) -> None:
        self.state: Dict[str, float] = {
            sym: self.base_price * (1 + random.uniform(-0.05, 0.05)) for sym in self.symbols
        }
        self.metadata: Dict[str, Dict[str, float | bool]] = {}

    def _advance_symbol(self, sym: str) -> SymbolMetrics:
        price = self.state[sym]
        drift = random.uniform(-0.002, 0.002)
        if random.random() < self.spike_chance:
            drift += random.choice([-0.02, 0.02])
        price *= (1 + drift)
        price = max(price, 0.1)
        self.state[sym] = price

        volume = abs(drift) * 5_000_000 + random.uniform(15_000_000, 50_000_000)  # $15M-$50M base volume
        open_interest = volume * random.uniform(2, 6)
        depth = volume * random.uniform(1.2, 3.5)

        atr_pct = abs(drift) * 500
        price_change_pct = drift * 6000
        trend_pct = drift * 40000

        bid_liq = max(20_000, depth * 0.45)  # satisfy min_liquidity_bid_size
        tick_pct = random.uniform(0.001, 0.05)
        listing_age = random.uniform(0, 10)  # within 10 days (to meet ≤14 day requirement)

        news_flag = random.random() < 0.7  # 70% chance of news flag
        news_score = random.uniform(7, 10) if news_flag else random.uniform(0, 5)
        self.metadata[sym] = {"news_flag": news_flag, "news_score": news_score, "listing_age_days": listing_age}

        return SymbolMetrics(
            symbol=sym,
            venue="futures",
            price=price,
            volume_usdt=volume,
            open_interest_usd=open_interest,
            max_leverage=random.randint(1, 20),
            bid_ask_spread_pct=random.uniform(0.02, 0.25),
            atr_5m_pct=atr_pct,
            price_change_1h_pct=price_change_pct,
            orderbook_depth_usd=depth,
            bid_liquidity_usd=bid_liq,
            tick_size_pct=tick_pct,
            trend_30d_pct=trend_pct,
            listing_age_days=listing_age,
            news_score=news_score,
            news_flag=news_flag,
        )

    def metrics_snapshot(self) -> Tuple[Dict[str, SymbolMetrics], Dict[str, SymbolMetrics], Dict[str, Dict[str, float | bool]]]:
        futures_metrics: Dict[str, SymbolMetrics] = {}
        spot_metrics: Dict[str, SymbolMetrics] = {}
        for sym in self.symbols:
            metric = self._advance_symbol(sym)
            futures_metrics[sym] = metric
            spot_metrics[sym] = replace(metric, venue="spot", open_interest_usd=0.0, max_leverage=0)
        return futures_metrics, spot_metrics, self.metadata.copy()


async def run_synthetic_screener(
    exchange: SyntheticExchange,
    manager: UniverseManager,
    config: RuntimeConfig,
    refresh_seconds: float,
) -> None:
    while True:
        futures_metrics, spot_metrics, metadata = exchange.metrics_snapshot()
        universes = config.universes or {}
        for strategy, filter_cfg in universes.items():
            symbols = UniverseScreener._apply_filter(filter_cfg, futures_metrics, spot_metrics, metadata)
            await manager.update(strategy, symbols)
        await asyncio.sleep(refresh_seconds)


async def synthetic_signal_stream(
    manager: UniverseManager,
    pipeline: StrategyPipeline,
    strategies: Iterable[str],
    interval: float,
    burst: int,
) -> None:
    while True:
        start = time.time()
        for strategy in strategies:
            _, symbols = await manager.current(strategy)
            if not symbols:
                continue
            for _ in range(burst):
                symbol = random.choice(symbols)
                side = random.choice(["BUY", "SELL"])
                sig = Signal(
                    strategy=strategy,
                    symbol=symbol,
                    side=side,
                    confidence=random.uniform(0.4, 0.99),
                    ttl=60,
                )
                await pipeline.queue.put((sig, time.time()))
        elapsed = time.time() - start
        await asyncio.sleep(max(0.0, interval - elapsed))


async def run_synthetic_runtime(args: argparse.Namespace) -> None:
    config = load_runtime_config(args.config)
    all_symbols: Set[str] = set()
    universes = config.universes or {}
    if not universes:
        universes = {"trend": None}
    for strategy, filter_cfg in universes.items():
        prefix = strategy[:2].upper()
        if filter_cfg is not None:
            for sym in filter_cfg.include_symbols:
                all_symbols.add(sym.upper())
        for i in range(args.symbols_per_strategy):
            all_symbols.add(_random_symbol(prefix, i))

    symbols = sorted(all_symbols)

    exchange = SyntheticExchange(symbols, base_price=args.base_price, spike_chance=args.spike_chance)

    portfolio = Portfolio(starting_cash=args.starting_cash)
    router = OrderRouter(default_client=DummyClient(), portfolio=portfolio)
    manager = UniverseManager(config)

    pipeline = StrategyPipeline(
        config=config,
        registry=StrategyRegistry(),  # empty to avoid websocket producers
        order_router=router,
        manager=manager,
    )

    pipeline._running = True  # noqa: SLF001
    consumer_task = asyncio.create_task(pipeline._consumer(), name="synthetic-consumer")  # noqa: SLF001

    screener_task = asyncio.create_task(
        run_synthetic_screener(exchange, manager, config, args.refresh_seconds),
        name="synthetic-screener",
    )

    signal_task = asyncio.create_task(
        synthetic_signal_stream(manager, pipeline, (config.universes or {}).keys(), args.signal_interval, args.burst),
        name="synthetic-signal-stream",
    )

    try:
        await asyncio.gather(consumer_task, screener_task, signal_task)
    except asyncio.CancelledError:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthetic runtime harness")
    parser.add_argument("--config", default="config/runtime.yaml", help="Path to runtime YAML config")
    parser.add_argument("--symbols-per-strategy", type=int, default=50)
    parser.add_argument("--refresh-seconds", type=float, default=15.0)
    parser.add_argument("--signal-interval", type=float, default=1.0)
    parser.add_argument("--burst", type=int, default=5, help="Signals per strategy per interval")
    parser.add_argument("--starting-cash", type=float, default=50_000.0)
    parser.add_argument("--base-price", type=float, default=100.0)
    parser.add_argument("--spike-chance", type=float, default=0.02)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_synthetic_runtime(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
