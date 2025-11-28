import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

from engine.strategies.symbol_scanner import SymbolScanner, SymbolScannerConfig
from engine.strategies.trend_follow import TrendStrategyConfig, TrendStrategyModule, TrendTF


class TestDynamicEcosystem(unittest.TestCase):
    def setUp(self):
        # Mock Param Client functions
        self.patcher_get = patch("engine.services.param_client.get_cached_params")
        self.patcher_update = patch("engine.services.param_client.update_param_features")
        self.mock_get = self.patcher_get.start()
        self.mock_update = self.patcher_update.start()

    def tearDown(self):
        self.patcher_get.stop()
        self.patcher_update.stop()

    def test_macro_brain_scanner(self):
        print("\n--- Testing Macro Brain (Scanner) ---")

        # Setup Scanner
        cfg = SymbolScannerConfig(
            enabled=True,
            universe=["BTCUSDT", "ETHUSDT"],
            interval_sec=60,
            interval="1m",
            lookback=50,
            top_n=2,
            min_volume_usd=0.0,
            min_atr_pct=0.0,
            weight_return=0.5,
            weight_trend=0.5,
            weight_vol=0.0,
            min_minutes_between_select=60,
            state_path="data/runtime/scanner_state.json",
        )
        scanner = SymbolScanner(cfg)

        # Mock _fetch_klines to return dummy data
        # BTCUSDT for features
        btc_data = [
            [1000, 100, 110, 90, 105, 1000, 0, 0, 0, 0, 0],  # High Vol
        ]
        # ETHUSDT for scoring
        eth_data = [
            [1000, 10, 11, 9, 10.5, 1000, 0, 0, 0, 0, 0],
        ]

        def side_effect(symbol):
            if symbol == "BTCUSDT":
                return btc_data
            if symbol == "ETHUSDT":
                return eth_data
            return []

        scanner._fetch_klines = MagicMock(side_effect=side_effect)

        # Mock Dynamic Params Response
        self.mock_get.return_value = {
            "params": {"weight_return": 0.1, "weight_trend": 0.2, "weight_vol": 0.7}
        }

        # Run Scan
        scanner._scan_once()

        # Verify Feature Update
        self.mock_update.assert_called()
        args = self.mock_update.call_args_list[0]
        print(f"Update Features Call: {args}")
        self.assertEqual(args[0][0], "symbol_scanner")
        self.assertEqual(args[0][1], "GLOBAL")
        self.assertIn("btc_vol", args[0][2])

        # Verify Weights Updated
        print(
            f"Scanner Weights: Ret={scanner.cfg.weight_return}, Trend={scanner.cfg.weight_trend}, Vol={scanner.cfg.weight_vol}"
        )
        self.assertEqual(scanner.cfg.weight_return, 0.1)
        self.assertEqual(scanner.cfg.weight_trend, 0.2)
        self.assertEqual(scanner.cfg.weight_vol, 0.7)

    @patch("engine.strategies.policy_hmm.get_regime")
    def test_micro_brain_strategy(self, mock_regime):
        print("\n--- Testing Micro Brain (TrendStrategy) ---")

        # Setup Strategy
        primary = TrendTF(interval="15m", fast=10, slow=20, rsi_length=14)
        secondary = TrendTF(interval="1h", fast=30, slow=40)
        regime = TrendTF(interval="4h", fast=50, slow=100)

        cfg = TrendStrategyConfig(
            enabled=True,
            dry_run=True,
            symbols=["BTCUSDT"],
            fetch_limit=100,
            refresh_sec=60,
            atr_length=14,
            atr_stop_mult=2.0,
            atr_target_mult=3.0,
            swing_lookback=20,
            rsi_long_min=40,
            rsi_long_max=70,
            rsi_exit=80,
            risk_pct=0.01,
            min_quote_usd=10.0,
            fallback_equity_usd=1000.0,
            cooldown_bars=5,
            allow_shorts=False,
            auto_tune_enabled=False,
            auto_tune_min_trades=10,
            auto_tune_interval=10,
            auto_tune_history=100,
            auto_tune_win_low=0.3,
            auto_tune_win_high=0.6,
            auto_tune_stop_min=1.0,
            auto_tune_stop_max=5.0,
            auto_tune_state_path="data/runtime/trend_auto_tune.json",
            primary=primary,
            secondary=secondary,
            regime=regime,
        )
        strategy = TrendStrategyModule(cfg)

        # Mock HMM
        mock_regime.return_value = {"p_bull": 0.8, "p_bear": 0.1}

        # Mock Dynamic Params Response
        self.mock_get.return_value = {"params": {"atr_stop_mult": 1.5, "rsi_long_max": 90.0}}

        # Mock _build_snapshot to return valid data
        strategy._build_snapshot = MagicMock(
            return_value={
                "primary_fast": 50000.0,
                "primary_slow": 49000.0,
                "rsi_primary": 50.0,
                "atr": 100.0,
                "regime_fast": 50000.0,
                "regime_slow": 49000.0,
                "stop": 49000.0,
                "target": 51000.0,
            }
        )

        # Run Tick
        strategy.handle_tick("BTCUSDT", 50000.0, 1234567890)

        # Verify Feature Update
        self.mock_update.assert_called()
        # Find the call for trend_strategy
        found = False
        for call in self.mock_update.call_args_list:
            if call[0][0] == "trend_strategy":
                found = True
                print(f"Update Features Call: {call}")
                self.assertEqual(call[0][1], "BTCUSDT")
                self.assertEqual(call[0][2]["hmm_bull"], 0.8)
                break
        self.assertTrue(found)

        # Verify Params Updated
        print(
            f"Strategy Params: Stop={strategy._params.atr_stop_mult}, RSI_Max={strategy._params.rsi_long_max}"
        )
        self.assertEqual(strategy._params.atr_stop_mult, 1.5)
        self.assertEqual(strategy._params.rsi_long_max, 90.0)


if __name__ == "__main__":
    unittest.main()
