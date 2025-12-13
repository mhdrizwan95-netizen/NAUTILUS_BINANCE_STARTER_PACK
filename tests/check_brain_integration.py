import unittest
import time
import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules["httpx"] = MagicMock()
mock_services = MagicMock()
sys.modules["engine.services"] = mock_services
sys.modules["engine.services.param_client"] = MagicMock()

# Mock HMM Policy to control Regime
mock_hmm = MagicMock()
sys.modules["engine.strategies.policy_hmm"] = mock_hmm

from engine.brain import NautilusBrain

class TestNautilusBrain(unittest.TestCase):
    def setUp(self):
        self.brain = NautilusBrain()
        
    def test_bull_regime_veto(self):
        """Test that negative sentiment vetoes a Bull Regime."""
        # Setup: HMM says BULL
        mock_hmm.get_regime.return_value = {"regime": "BULL", "conf": 0.9}
        
        # Scenario 1: Sentiment is Neutral/Positive (0.2)
        # Should result in BUY
        self.brain.update_sentiment("BTC", 0.2, time.time())
        side, size, meta = self.brain.get_decision("BTC", 50000.0)
        self.assertEqual(side, "BUY")
        self.assertEqual(meta["regime"], "BULL")
        
        # Scenario 2: Sentiment is Negative Veto (< -0.5)
        # Should result in None (Veto)
        self.brain.update_sentiment("BTC", -0.8, time.time())
        side, size, meta = self.brain.get_decision("BTC", 50000.0)
        self.assertIsNone(side)
        self.assertIn("VETO", meta["brain_reason"])
        
    def test_chop_regime_breakout(self):
        """Test that extreme sentiment can trigger trade in Chop."""
        # Setup: HMM says CHOP
        mock_hmm.get_regime.return_value = {"regime": "CHOP", "conf": 0.5}
        
        # Scenario 1: Sentiment Neutral
        self.brain.update_sentiment("ETH", 0.1, time.time())
        side, size, meta = self.brain.get_decision("ETH", 3000.0)
        self.assertIsNone(side)
        
        # Scenario 2: Extreme Bullish Sentiment (> 0.8)
        self.brain.update_sentiment("ETH", 0.9, time.time())
        side, size, meta = self.brain.get_decision("ETH", 3000.0)
        self.assertEqual(side, "BUY")
        self.assertIn("Breakout", meta["brain_reason"])

if __name__ == '__main__':
    unittest.main()
