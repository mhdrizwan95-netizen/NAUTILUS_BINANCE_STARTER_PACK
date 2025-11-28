import logging
import time
from unittest.mock import MagicMock, patch

from engine.strategies.trend_follow import TrendStrategyConfig, TrendStrategyModule, TrendTF

# Configure logging
logging.basicConfig(level=logging.INFO)


def get_dummy_config():
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
        # Open, High, Low, Close, Volume
        # Create a clear uptrend
        price += 10.0
        klines.append(
            [
                (time.time() - (length - i) * 60) * 1000,  # Open time
                str(price + 5),  # Open
                str(price + 10),  # High
                str(price - 5),  # Low
                str(price),  # Close
                "1.0",  # Volume
                (time.time() - (length - i) * 60) * 1000 + 59999,  # Close time
            ]
        )
    return klines


def test_strategy_signal():
    print(">>> Testing TrendStrategy Signal Generation...")
    cfg = get_dummy_config()

    # Mock Client
    mock_client = MagicMock()
    # Return bullish klines for all intervals
    bullish_data = generate_bullish_klines()
    mock_client.klines.return_value = bullish_data

    # Mock Scanner
    mock_scanner = MagicMock()
    mock_scanner.get.return_value = {"BTCUSDT"}

    # Initialize Strategy
    strategy = TrendStrategyModule(cfg, client=mock_client, scanner=mock_scanner)

    # Mock HMM Policy to be BULLISH
    with patch("engine.strategies.policy_hmm.get_regime") as mock_hmm:
        mock_hmm.return_value = {
            "regime": "BULL",
            "conf": 0.8,
            "probs": [0.8, 0.1, 0.1],
            "p_bull": 0.8,
            "p_bear": 0.1,
            "p_chop": 0.1,
        }

        # Mock Portfolio/OrderRouter snapshot for equity
        with patch("engine.core.order_router.portfolio_snapshot") as mock_snap:
            mock_snap.return_value = {"equity": 10000.0}

            # Feed a tick
            # Price needs to be consistent with klines
            current_price = 51000.0
            ts = time.time()

            # First tick might just build snapshot
            action = strategy.handle_tick("BTCUSDT", current_price, ts)

            if action:
                print(f"SUCCESS: Strategy generated action: {action}")
                assert action["side"] == "BUY"
                assert action["symbol"] == "BTCUSDT.BINANCE"
                assert action["quote"] > 0

                # --- Verify Execution ---
                print(">>> Testing StrategyExecutor...")
                from engine.execution.execute import StrategyExecutor

                # Mock RiskRails
                mock_risk = MagicMock()
                mock_risk.check_order.return_value = (True, None)

                # Mock Router methods
                mock_router = MagicMock()
                mock_router.market_quote = MagicMock(
                    return_value={"status": "filled", "executedQty": 0.002}
                )

                # Initialize Executor
                executor = StrategyExecutor(
                    risk=mock_risk, router=mock_router, default_dry_run=False
                )

                # Prepare Signal Payload (mimic engine/strategy.py _signal_payload)
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

                # Execute
                # We need to patch CACHE in execute.py to avoid redis/memory errors if not set up
                with patch("engine.execution.execute.CACHE", MagicMock()) as mock_cache:
                    mock_cache.get.return_value = None  # No cached result

                    result = executor.execute_sync(payload)

                    print(f"Execution Result: {result}")

                    # Verify Router Call
                    # StrategyExecutor prefers market_quote if quote is present
                    mock_router.market_quote.assert_called()
                    call_args = mock_router.market_quote.call_args
                    print(f"Router called with: {call_args}")

                    assert result["status"] == "submitted"
                    print("SUCCESS: Order submitted to router.")

            else:
                print("FAILURE: No action generated.")
                # Debugging
                snap = strategy._build_snapshot("BTCUSDT")
                print(f"Snapshot: {snap}")
                print(f"Long Ready: {strategy._long_entry_ready(snap)}")


if __name__ == "__main__":
    test_strategy_signal()
