from __future__ import annotations

import asyncio
from typing import Dict

import pytest

from engine.runtime.config import RuntimeConfig, UniverseFilterConfig
from engine.runtime.universe import SymbolMetrics, UniverseManager


@pytest.mark.asyncio
async def test_universe_manager_updates() -> None:
    cfg = RuntimeConfig()
    manager = UniverseManager(cfg)
    version, symbols = await manager.current("trend")
    assert symbols == tuple(sym.upper() for sym in cfg.symbols.core)

    await manager.update("trend", ["BTCUSDT", "ETHUSDT"])
    new_version = await manager.wait_for_update("trend", version)
    assert new_version != version
    version, symbols = await manager.current("trend")
    assert symbols == ("BTCUSDT", "ETHUSDT")


def test_universe_filter_application() -> None:
    filter_cfg = UniverseFilterConfig.from_dict(
        "test",
        {
            "venues": ["futures"],
            "min_24h_volume_usdt": 1_000_000,
            "min_price_usdt": 1.0,
            "min_futures_open_interest_usdt": 1_000_000,
            "min_leverage_supported": 2,
            "min_30d_trend_pct": 5,
            "max_bid_ask_spread_pct": 0.5,
            "min_5m_atr_pct": 0.2,
            "min_price_change_pct_last_1h": 0.5,
            "min_liquidity_bid_size": 10_000,
            "min_orderbook_depth_usdt": 20_000,
            "min_tick_size_pct": 0.001,
            "sort_by": ["futures_open_interest_usdt", "24h_volume_usdt"],
            "max_symbols": 2,
            "exclude_suffixes": ["UP", "DOWN"],
        },
    )

    fut_metrics = {
        "BTCUSDT": SymbolMetrics(
            "BTCUSDT",
            "futures",
            price=25000.0,
            volume_usdt=50_000_000.0,
            open_interest_usd=3_000_000.0,
            max_leverage=20,
            bid_ask_spread_pct=0.1,
            atr_5m_pct=0.8,
            price_change_1h_pct=3.0,
            orderbook_depth_usd=400_000.0,
            bid_liquidity_usd=200_000.0,
            tick_size_pct=0.01,
            trend_30d_pct=15.0,
            listing_age_days=5.0,
        ),
        "ETHUSDT": SymbolMetrics(
            "ETHUSDT",
            "futures",
            price=1600.0,
            volume_usdt=20_000_000.0,
            open_interest_usd=2_500_000.0,
            max_leverage=15,
            bid_ask_spread_pct=0.2,
            atr_5m_pct=0.5,
            price_change_1h_pct=1.5,
            orderbook_depth_usd=150_000.0,
            bid_liquidity_usd=90_000.0,
            tick_size_pct=0.02,
            trend_30d_pct=8.0,
            listing_age_days=40.0,
        ),
        "DOGEUSDT": SymbolMetrics(
            "DOGEUSDT",
            "futures",
            price=0.07,
            volume_usdt=5_000_000.0,
            open_interest_usd=80_000.0,
            max_leverage=10,
        ),
        "AVAUP": SymbolMetrics(
            "AVAUP",
            "futures",
            price=4.0,
            volume_usdt=10_000_000.0,
            open_interest_usd=200_000.0,
            max_leverage=5,
        ),
    }
    spot_metrics: Dict[str, SymbolMetrics] = {}

    from engine.runtime.universe import UniverseScreener

    metadata = {"BTCUSDT": {"news_score": 8.0, "has_major_news_flag": True}}

    symbols = UniverseScreener._apply_filter(  # type: ignore[arg-type]
        filter_cfg, fut_metrics, spot_metrics, metadata
    )
    assert symbols == ["BTCUSDT", "ETHUSDT"]
