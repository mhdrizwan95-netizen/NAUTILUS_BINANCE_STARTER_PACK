from __future__ import annotations

import argparse
import asyncio
import math
from dataclasses import dataclass
from typing import Any, List, Optional

from engine.strategies.scalping import ScalpConfig, ScalpStrategyModule
from engine.strategies.momentum_breakout import MomentumBreakout, MomentumConfig
from engine.strategies.meme_coin_sentiment import MemeCoinConfig, MemeCoinSentiment


@dataclass
class _Clock:
    now: float = 1_700_000_000.0

    def time(self) -> float:
        return self.now


# ---- Scalper scenario -----------------------------------------------------

def run_scalper() -> None:
    cfg = ScalpConfig(
        enabled=True,
        dry_run=True,
        symbols=("BTCUSDT",),
        window_sec=90.0,
        min_samples=20,
        min_range_bps=12.0,
        lower_threshold=0.2,
        upper_threshold=0.8,
        rsi_length=3,
        stop_bps=35.0,
        take_profit_bps=55.0,
        quote_usd=150.0,
        cooldown_sec=15.0,
        allow_shorts=False,
    )
    module = ScalpStrategyModule(cfg)
    prices = [42_000 + math.sin(i / 5.0) * 80 for i in range(240)]
    ts = 0.0
    for price in prices:
        decision = module.handle_tick("BTCUSDT.BINANCE", price, ts)
        ts += 1.0
        if decision:
            print(f"[SCALP] t={ts:.0f} price={price:.2f} -> {decision['side']} {decision['quote']:.2f} {decision['market']}")


# ---- Momentum scenario ----------------------------------------------------

class _RiskStub:
    def check_order(self, *, symbol: str, side: str, quote: float, quantity: Optional[float], market: Optional[str] = None):
        return True, {}


class _MomentumRouter:
    def __init__(self, bars: List[List[float]]) -> None:
        self._bars = bars
        self.orders: list[tuple[str, str, float, Optional[str]]] = []

    def exchange_client(self):
        class _Client:
            def __init__(self, bars: List[List[float]]) -> None:
                self._bars = bars

            async def klines(self, symbol: str, interval: str = "1m", limit: int = 30):
                return self._bars[-limit:]

        return _Client(self._bars)

    async def market_quote(self, symbol: str, side: str, quote: float, market: Optional[str] = None):
        self.orders.append((symbol, side, quote, market))
        last = self._bars[-1][4]
        qty = quote / last
        return {"avg_fill_price": last, "filled_qty_base": qty}

    async def amend_stop_reduce_only(self, *args, **kwargs):
        return None

    async def place_reduce_only_limit(self, *args, **kwargs):
        return None

    def trade_symbols(self) -> List[str]:
        return ["ABCUSDT"]


def _momentum_bars() -> List[List[float]]:
    bars: List[List[float]] = []
    price = 50.0
    for _ in range(40):
        high = price * 1.01
        low = price * 0.99
        close = price * 1.002
        bars.append([0, price, high, low, close, 1200, 0, 220000])
        price = close
    return bars


async def run_momentum_async() -> None:
    bars = _momentum_bars()
    router = _MomentumRouter(bars)
    cfg = MomentumConfig(
        enabled=True,
        dry_run=False,
        use_scanner=False,
        symbols=["ABCUSDT"],
        scanner_top_n=3,
        interval_sec=30.0,
        lookback_bars=8,
        pct_move_threshold=0.01,
        volume_window=3,
        volume_baseline_window=6,
        volume_multiplier=1.1,
        atr_length=5,
        atr_interval="1m",
        stop_atr_mult=1.4,
        trail_atr_mult=1.1,
        take_profit_pct=0.03,
        cooldown_sec=120.0,
        notional_usd=150.0,
        max_extension_pct=0.18,
        prefer_futures=True,
        leverage_major=2,
        leverage_default=2,
        max_signals_per_cycle=2,
        min_quote_volume_usd=50_000.0,
        default_market="futures",
    )
    momentum = MomentumBreakout(router, _RiskStub(), cfg=cfg, scanner=None, clock=_Clock())
    plan = await momentum._evaluate_symbol("ABCUSDT")
    if plan is None:
        print("[MOMENTUM] No trigger for synthetic data")
        return
    print(
        f"[MOMENTUM] trigger symbol={plan.symbol} price={plan.price:.4f} stop={plan.stop_price:.4f} tp={plan.take_profit:.4f} market={plan.market}"
    )
    await momentum._execute(plan)
    if router.orders:
        print(f"[MOMENTUM] executed order -> {router.orders[0]}")


# ---- Meme sentiment scenario ----------------------------------------------

class _MemeRouter:
    def __init__(self) -> None:
        self._portfolio = type("_P", (), {"state": type("_S", (), {"equity": 2_000.0})()})()
        self.calls: list[tuple[str, str, float, Optional[str]]] = []

    async def market_quote(self, symbol: str, side: str, notional: float, market: Optional[str] = None):
        self.calls.append((symbol, side, notional, market))
        return {"avg_fill_price": 0.25, "filled_qty_base": notional / 0.25}


class _MemeRisk:
    def check_order(self, *, symbol: str, side: str, quote: float, quantity: Optional[float], market: Optional[str] = None):
        return True, {}


class _MemeRest:
    async def book_ticker(self, symbol: str):
        return {"bidPrice": "0.24", "askPrice": "0.26"}


async def run_meme_async() -> None:
    cfg = MemeCoinConfig(
        enabled=True,
        dry_run=False,
        min_priority=0.8,
        min_social_score=1.5,
        min_mentions=5,
        min_velocity_score=1.0,
        deny_keywords=(),
        allow_sources=(),
        quote_priority=("USDT",),
        default_market="spot",
    )
    strat = MemeCoinSentiment(_MemeRouter(), _MemeRisk(), _MemeRest(), cfg, clock=_Clock())
    event = {
        "source": "twitter_firehose",
        "priority": 0.92,
        "asset_hints": ["DOGE"],
        "payload": {
            "text": "DOGE rockets on volume",
            "metrics": {
                "mention_count": 120,
                "like_count": 900,
                "retweet_count": 310,
                "reply_count": 140,
            },
            "social_velocity": 6.0,
            "price_change_pct": 12.0,
        },
    }
    await strat.on_external_event(event)
    if strat.router.calls:
        print(f"[MEME] execution -> {strat.router.calls[0]}")
    else:
        print("[MEME] no execution for synthetic event")


# ---- CLI ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic backtest harness for key strategy modules")
    parser.add_argument("module", choices=["scalp", "momentum", "meme"], help="Module to exercise")
    args = parser.parse_args()

    if args.module == "scalp":
        run_scalper()
    elif args.module == "momentum":
        asyncio.run(run_momentum_async())
    else:
        asyncio.run(run_meme_async())


if __name__ == "__main__":
    main()
