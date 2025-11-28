import logging
import math
import time
from unittest.mock import MagicMock, patch

from engine.execution.execute import StrategyExecutor
from engine.strategies.momentum_realtime import MomentumRealtimeConfig, MomentumStrategyModule
from engine.strategies.scalping import ScalpConfig, ScalpStrategyModule
from engine.strategies.trend_follow import TrendStrategyConfig, TrendStrategyModule, TrendTF

# Configure logging
logging.basicConfig(level=logging.INFO)


# --- Trend Strategy Helpers ---
def get_trend_config():
    return TrendStrategyConfig(
        enabled=True,
        dry_run=True,
        symbols=["BTCUSDT"],
        fetch_limit=100,
        refresh_sec=60,
        atr_length=14,
        atr_stop_mult=2.0,
        atr_target_mult=3.0,
        swing_lookback=20,
        rsi_long_min=40.0,
        rsi_long_max=100.0,
        rsi_exit=80.0,
        risk_pct=0.01,
        min_quote_usd=10.0,
        fallback_equity_usd=1000.0,
        cooldown_bars=1,
        allow_shorts=False,
        auto_tune_enabled=False,
        auto_tune_min_trades=10,
        auto_tune_interval=3600,
        auto_tune_history=30,
        auto_tune_win_low=0.4,
        auto_tune_win_high=0.6,
        auto_tune_stop_min=1.0,
        auto_tune_stop_max=5.0,
        auto_tune_state_path="/tmp/trend_state.json",
        primary=TrendTF(interval="15m", fast=10, slow=20, rsi_length=14),
        secondary=TrendTF(interval="1h", fast=10, slow=20, rsi_length=14),
        regime=TrendTF(interval="4h", fast=10, slow=20, rsi_length=14),
    )


def generate_bullish_klines(length=100, start_price=50000.0):
    klines = []
    price = start_price
    for i in range(length):
        price += 10.0
        klines.append(
            [
                (time.time() - (length - i) * 60) * 1000,
                str(price + 5),
                str(price + 10),
                str(price - 5),
                str(price),
                "1.0",
                (time.time() - (length - i) * 60) * 1000 + 59999,
            ]
        )
    return klines


# --- Scalp Strategy Helpers ---
def get_scalp_config():
    return ScalpConfig(
        enabled=True,
        dry_run=True,
        symbols=("BTCUSDT",),
        window_sec=60.0,
        min_ticks=3,
        min_range_bps=3.0,
        lower_threshold=0.45,
        upper_threshold=0.55,
        rsi_length=14,
        rsi_buy=30.0,
        rsi_sell=70.0,
        stop_bps=10.0,
        take_profit_bps=20.0,
        quote_usd=100.0,
        cooldown_sec=0.0,
        allow_shorts=True,
        prefer_futures=True,
        signal_ttl_sec=5.0,
        max_signals_per_min=10,
        imbalance_threshold=0.3,
        max_spread_bps=5.0,
        min_depth_usd=1000.0,
        momentum_ticks=3,
        fee_bps=1.0,
        book_stale_sec=5.0,
    )


# --- Momentum Strategy Helpers ---
def get_momentum_config():
    return MomentumRealtimeConfig(
        enabled=True,
        dry_run=True,
        symbols=("BTCUSDT",),
        window_sec=60.0,
        baseline_sec=300.0,
        min_ticks=3,
        pct_move_threshold=0.0001,  # 1 bp for easy trigger
        volume_spike_ratio=1.5,
        cooldown_sec=0.0,
        quote_usd=100.0,
        stop_loss_pct=0.001,
        trail_pct=0.001,
        take_profit_pct=0.002,
        allow_shorts=True,
        prefer_futures=True,
    )


# --- Execution Helper ---
def verify_execution(action, strategy_name):
    print(f">>> Verifying Execution for {strategy_name}...")
    mock_risk = MagicMock()
    mock_risk.check_order.return_value = (True, None)
    mock_router = MagicMock()
    mock_router.market_quote = MagicMock(return_value={"status": "filled", "executedQty": 0.002})

    executor = StrategyExecutor(risk=mock_risk, router=mock_router, default_dry_run=False)

    payload = {
        "strategy": action["tag"],
        "symbol": action["symbol"],
        "side": action["side"],
        "quote": action["quote"],
        "quantity": None,
        "dry_run": False,
        "meta": action["meta"],
        "market": action.get("market"),
        "tag": action["tag"],
        "ts": time.time(),
    }

    with patch("engine.execution.execute.CACHE", MagicMock()) as mock_cache:
        mock_cache.get.return_value = None
        result = executor.execute_sync(payload)
        print(f"Execution Result: {result}")
        assert result["status"] == "submitted"
        print(f"SUCCESS: {strategy_name} order submitted.")


# --- Tests ---


def test_trend_strategy():
    print("\n=== Testing TrendStrategy ===")
    cfg = get_trend_config()
    mock_client = MagicMock()
    mock_client.klines.return_value = generate_bullish_klines()
    mock_scanner = MagicMock()
    mock_scanner.get.return_value = {"BTCUSDT"}

    strategy = TrendStrategyModule(cfg, client=mock_client, scanner=mock_scanner)

    with (
        patch("engine.strategies.policy_hmm.get_regime") as mock_hmm,
        patch("engine.core.order_router.portfolio_snapshot") as mock_snap,
    ):
        mock_hmm.return_value = {"regime": "BULL", "conf": 0.8}
        mock_snap.return_value = {"equity": 10000.0}

        action = strategy.handle_tick("BTCUSDT", 51000.0, time.time())
        if action:
            print(f"Signal: {action}")
            verify_execution(action, "TrendStrategy")
        else:
            print("FAILURE: No Trend signal.")


def test_scalp_strategy():
    print("\n=== Testing ScalpStrategy ===")
    import os

    os.environ["SYMBOL_SCANNER_ENABLED"] = "true"

    cfg = get_scalp_config()
    mock_scanner = MagicMock()
    # StrategyUniverse calls current_universe or get_selected
    mock_scanner.current_universe.return_value = ["BTCUSDT"]
    mock_scanner.get_selected.return_value = ["BTCUSDT"]

    strategy = ScalpStrategyModule(cfg, scanner=mock_scanner)
    print(f"Universe allowed: {strategy._universe.get('scalp')}")

    # Simulate Order Book (Healthy)
    strategy.handle_book(
        "BTCUSDT.BINANCE",
        bid_price=50000.0,
        ask_price=50001.0,
        bid_qty=10.0,
        ask_qty=1.0,  # High bid imbalance -> Bullish
    )

    # Simulate Ticks (Range bound but oversold/bullish flow)
    # We need enough ticks to form a range and RSI
    base_price = 50000.5
    ts = time.time()

    # Feed history
    # RSI needs 14 periods. We feed 30.
    # To trigger oversold (RSI < 30), we need a downtrend.
    # But we want a BUY signal, which requires:
    # 1. Price <= lower_threshold (in range)
    # 2. Bullish Flow (Imbalance > 0.3) OR Oversold

    # Let's create a range where price is low, but book is bullish.

    # 1. Fill window with range data
    # Range needs to be at least 3 bps.
    # Price ~50000. 3 bps = 15.0.
    # We set range 49980 to 50020 (40 pts = ~8 bps)
    high = 50020.0
    low = 49980.0
    span = high - low

    # 1. Fill window with range data
    # Range needs to be at least 3 bps.
    # Price ~50000. 3 bps = 15.0.
    # We set range 49980 to 50020 (40 pts = ~8 bps)
    high = 50020.0
    low = 49980.0
    span = high - low

    for i in range(30):
        # Keep price HIGH (above 0.55 pos) to avoid BUY signals in loop
        # Pos > 0.55.
        # Low + Span*0.8 = 49980 + 32 = 50012.
        p = low + (span * 0.8) + math.sin(i) * 2
        strategy.handle_tick("BTCUSDT.BINANCE", p, ts - (60 - i))

    # 2. Trigger Tick
    # Price needs to be <= lower_threshold (0.45) of range
    # Low = 49980, High = 50020. Span = 40.
    # Threshold = 49980 + 40*0.45 = 49998.
    # We set price to 49985.

    current_price = 49985.0
    action = strategy.handle_tick("BTCUSDT.BINANCE", current_price, ts)

    if action:
        print(f"Signal: {action}")
        verify_execution(action, "ScalpStrategy")
    else:
        print("FAILURE: No Scalp signal.")
        # Debug
        print(f"Book Imbalance: {strategy._books.get('BTCUSDT').imbalance}")
        print(f"Windows: {len(strategy._windows['BTCUSDT'])}")

        # Manual Calc
        prices = [p for _, p in strategy._windows["BTCUSDT"]]
        if prices:
            low = min(prices)
            high = max(prices)
            span = high - low
            range_bps = (span / current_price) * 10000 if current_price > 0 else 0
            price_pos = (current_price - low) / span if span > 0 else 0.5
            print(
                f"DEBUG SCALP: Low={low}, High={high}, Span={span}, RangeBps={range_bps}, Pos={price_pos}"
            )

            # RSI
            from engine.strategies.scalping import _rsi

            rsi_val = _rsi(prices, cfg.rsi_length)
            print(f"DEBUG SCALP: RSI={rsi_val}")


def test_momentum_strategy():
    print("\n=== Testing MomentumStrategy ===")
    import os

    os.environ["SYMBOL_SCANNER_ENABLED"] = "true"

    cfg = get_momentum_config()
    mock_scanner = MagicMock()
    mock_scanner.current_universe.return_value = ["BTCUSDT"]
    mock_scanner.get_selected.return_value = ["BTCUSDT"]

    strategy = MomentumStrategyModule(cfg, scanner=mock_scanner)
    print(f"Universe allowed: {strategy._universe.get('momentum_rt')}")

    ts = time.time()
    base_price = 50000.0

    # Feed baseline (low volatility)
    # Baseline window is 300s. Feed enough points.
    # Ensure baseline high/low are tight.
    for i in range(50):
        # Very small noise
        p = base_price + math.sin(i) * 0.1
        strategy.handle_tick("BTCUSDT.BINANCE", p, ts - 300 + i * 5, volume=1.0)

    # Trigger: Price Jump + Volume Spike
    # Move > 0.01% (5.0) -> 50010.0
    # Baseline High is ~50000.1
    # We jump to 50050.0 (> 0.1% move, > 5bps hardcoded threshold)
    # Volume > 1.5x baseline (1.0) -> 10.0

    trigger_price = 50050.0
    action = strategy.handle_tick("BTCUSDT.BINANCE", trigger_price, ts, volume=10.0)

    if action:
        print(f"Signal: {action}")
        verify_execution(action, "MomentumStrategy")
    else:
        print("FAILURE: No Momentum signal.")
        # Debug
        print(f"Windows: {len(strategy._windows['BTCUSDT'])}")

        # Manual Calc
        from engine.strategies.momentum_realtime import _recent

        window = strategy._windows["BTCUSDT"]
        fast_cutoff = ts - cfg.window_sec
        fast_points = list(_recent(window, fast_cutoff))
        if fast_points:
            prices = [p for _, p, _ in fast_points]
            lows = min(prices)
            highs = max(prices)

            baseline_prices = [p for ts_val, p, _ in window if ts_val < fast_cutoff]
            baseline_high = max(baseline_prices) if baseline_prices else highs
            baseline_low = min(baseline_prices) if baseline_prices else lows

            effective_low = min(lows, baseline_low)
            pct_move_up = (
                (trigger_price - effective_low) / effective_low
                if trigger_price > effective_low
                else 0.0
            )

            print(
                f"DEBUG MOMO: Lows={lows}, Highs={highs}, BaseLow={baseline_low}, EffLow={effective_low}, MoveUp={pct_move_up*100:.4f}%"
            )
            print(f"DEBUG MOMO: Threshold={cfg.pct_move_threshold*100:.4f}%")

            # Volume
            recent_volume = sum(v for _, _, v in fast_points)
            baseline_volumes = [v for ts_val, _, v in window if ts_val < fast_cutoff and v > 0.0]
            if baseline_volumes:
                baseline_avg_volume = sum(baseline_volumes) / max(len(baseline_volumes), 1)
            else:
                baseline_avg_volume = 0

            print(f"DEBUG MOMO: RecentVol={recent_volume}, BaseAvg={baseline_avg_volume}")
        # Check internal state if possible (hard without access to local vars)


if __name__ == "__main__":
    test_trend_strategy()
    test_scalp_strategy()
    test_momentum_strategy()
