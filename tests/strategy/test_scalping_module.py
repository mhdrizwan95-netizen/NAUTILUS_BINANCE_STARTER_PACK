import math

from prometheus_client import generate_latest

from engine.strategies.scalping import ScalpConfig, ScalpStrategyModule


class FakeClock:
    def __init__(self) -> None:
        self._now = 0.0

    def time(self) -> float:
        return self._now

    def set(self, value: float) -> None:
        self._now = float(value)


def _cfg(**overrides) -> ScalpConfig:
    base = dict(
        enabled=True,
        dry_run=True,
        symbols=("BTCUSDT",),
        window_sec=25.0,
        min_ticks=4,
        min_range_bps=6.0,
        lower_threshold=0.25,
        upper_threshold=0.75,
        rsi_length=2,
        rsi_buy=20.0,
        rsi_sell=80.0,
        stop_bps=10.0,
        take_profit_bps=18.0,
        quote_usd=50.0,
        cooldown_sec=5.0,
        allow_shorts=True,
        prefer_futures=True,
        signal_ttl_sec=30.0,
        max_signals_per_min=5,
        imbalance_threshold=0.15,
        max_spread_bps=5.0,
        min_depth_usd=10_000.0,
        momentum_ticks=2,
        fee_bps=6.5,
        book_stale_sec=5.0,
    )
    base.update(overrides)
    return ScalpConfig(**base)


def _seed_ticks(module: ScalpStrategyModule, clock: FakeClock, prices: list[float]) -> None:
    start = clock.time()
    for idx, price in enumerate(prices):
        clock.set(start + idx * 4.0)
        module.handle_tick("BTCUSDT.BINANCE", price, ts=clock.time())


def test_scalp_generates_long_signal_with_orderbook_pressure() -> None:
    cfg = _cfg()
    clock = FakeClock()
    module = ScalpStrategyModule(cfg, clock=clock, slip_predictor=lambda feats: 2.0)

    clock.set(0.0)
    module.handle_book("BTCUSDT.BINANCE", bid_price=100.0, ask_price=100.04, bid_qty=120.0, ask_qty=60.0, ts=clock.time())

    _seed_ticks(module, clock, [100.2, 99.92, 99.95, 99.96])
    clock.set(16.0)
    module.handle_book("BTCUSDT.BINANCE", bid_price=99.97, ask_price=100.0, bid_qty=140.0, ask_qty=55.0, ts=clock.time())

    signal = module.handle_tick("BTCUSDT.BINANCE", 99.97, ts=clock.time())
    assert signal is not None
    assert signal["side"] == "BUY"
    assert signal["symbol"] == "BTCUSDT.BINANCE"
    assert signal["market"] == "futures"
    meta = signal["meta"]
    assert meta["order_book_imbalance"] > 0.0
    assert meta["signal_expires_at"] > clock.time()
    assert math.isclose(meta["stop_price"], 99.97 * (1 - cfg.stop_bps / 10_000.0), rel_tol=1e-6)
    assert math.isclose(meta["take_profit"], 99.97 * (1 + cfg.take_profit_bps / 10_000.0), rel_tol=1e-6)

    metrics_blob = generate_latest().decode()
    assert "scalp_signals_total" in metrics_blob
    assert "scalp_signal_edge_bp" in metrics_blob


def test_scalp_blocks_when_edge_eroded_by_slippage() -> None:
    cfg = _cfg()
    clock = FakeClock()
    module = ScalpStrategyModule(cfg, clock=clock, slip_predictor=lambda feats: 30.0)

    clock.set(0.0)
    module.handle_book("BTCUSDT.BINANCE", bid_price=100.0, ask_price=100.02, bid_qty=90.0, ask_qty=40.0, ts=clock.time())
    _seed_ticks(module, clock, [100.15, 99.9, 99.92, 99.94])
    clock.set(16.0)
    module.handle_book("BTCUSDT.BINANCE", bid_price=99.95, ask_price=99.97, bid_qty=95.0, ask_qty=40.0, ts=clock.time())

    signal = module.handle_tick("BTCUSDT.BINANCE", 99.95, ts=clock.time())
    assert signal is None


def test_scalp_respects_rate_limit() -> None:
    cfg = _cfg(cooldown_sec=0.0, max_signals_per_min=1)
    clock = FakeClock()
    module = ScalpStrategyModule(cfg, clock=clock, slip_predictor=lambda feats: 1.0)

    def _prep(now: float) -> None:
        clock.set(now)
        module.handle_book("BTCUSDT.BINANCE", bid_price=100.0, ask_price=100.01, bid_qty=150.0, ask_qty=40.0, ts=clock.time())
        _seed_ticks(module, clock, [100.12, 99.88, 99.9, 99.92])
        clock.set(now + 16.0)
        module.handle_book("BTCUSDT.BINANCE", bid_price=99.93, ask_price=99.95, bid_qty=160.0, ask_qty=50.0, ts=clock.time())

    _prep(0.0)
    first = module.handle_tick("BTCUSDT.BINANCE", 99.93, ts=clock.time())
    assert first is not None

    _prep(30.0)
    second = module.handle_tick("BTCUSDT.BINANCE", 99.93, ts=clock.time())
    assert second is None
