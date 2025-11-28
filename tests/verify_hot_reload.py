import unittest
from unittest.mock import MagicMock, patch

from engine.strategies import policy_hmm


class TestHotReload(unittest.TestCase):
    def setUp(self):
        # Reset the global _model variable before each test
        policy_hmm._model = None

    @patch("engine.strategies.policy_hmm._load_model")
    def test_reload_model(self, mock_load_model):
        # Setup mock
        mock_model_1 = MagicMock(name="ModelV1")
        mock_model_2 = MagicMock(name="ModelV2")
        mock_load_model.side_effect = [mock_model_1, mock_model_2]

        # 1. First access loads the model
        model1 = policy_hmm.model()
        self.assertEqual(model1, mock_model_1)
        mock_load_model.assert_called_once()

        # 2. Second access should return cached model
        model1_cached = policy_hmm.model()
        self.assertEqual(model1_cached, mock_model_1)
        self.assertEqual(mock_load_model.call_count, 1)

        # 3. Trigger reload
        print("\nTriggering reload_model...")
        policy_hmm.reload_model({"event": "model.promoted"})

        # 4. Next access should load new model
        model2 = policy_hmm.model()
        self.assertEqual(model2, mock_model_2)
        self.assertEqual(mock_load_model.call_count, 2)
        print("✅ Test Passed: Model reloaded successfully.")


if __name__ == "__main__":
    unittest.main()
