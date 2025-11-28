import unittest
from unittest.mock import MagicMock

from engine.adapters.binance_adapter import BinanceVenue


class TestBinanceAdapterExceptions(unittest.TestCase):
    def test_positions_raises_exception(self):
        # Mock the client to raise an exception
        mock_client = MagicMock()
        mock_client.positions.side_effect = ValueError("API Error")

        adapter = BinanceVenue(mock_client)

        # Verify that the exception is raised and not suppressed
        with self.assertRaises(ValueError):
            adapter.positions()

    def test_account_snapshot_raises_exception(self):
        mock_client = MagicMock()
        mock_client.account_snapshot.side_effect = RuntimeError("Connection Failed")

        adapter = BinanceVenue(mock_client)

        with self.assertRaises(RuntimeError):
            adapter.account_snapshot()


if __name__ == "__main__":
    unittest.main()
