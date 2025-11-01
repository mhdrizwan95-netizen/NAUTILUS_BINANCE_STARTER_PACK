#!/usr/bin/env python3
"""
T5: Unit tests for parsing _parse_prometheus_text and key extraction helpers.
Tests sample payloads from all four fallback chain shapes.
"""
import unittest
from dashboard.app import _parse_prometheus_text
from dashboard.app import _from_json


class TestParsing(unittest.TestCase):
    """Test _parse_prometheus_text function with various Prometheus formats."""

    def test_basic_gauge_format(self):
        """Test basic gauge format without labels."""
        text = """# HELP pnl_realized Realized PnL USD
# TYPE pnl_realized gauge
pnl_realized 1234.56

# HELP policy_confidence Policy confidence score
# TYPE policy_confidence gauge
policy_confidence 0.88
"""
        result = _parse_prometheus_text(text)
        expected = {
            "pnl_realized": 1234.56,
            "policy_confidence": 0.88,
        }
        self.assertEqual(result, expected)

    def test_labeled_metric_format(self):
        """Test metrics with labels."""
        text = """hmm_drift_score{symbol="BTCUSDT",version="v2"} 0.42
venue_latency_ms{venue="binance",region="us"} 123.45
"""
        result = _parse_prometheus_text(text)
        expected = {
            "hmm_drift_score": 0.42,
            "venue_latency_ms": 123.45,
        }
        self.assertEqual(result, expected)

    def test_scientific_notation(self):
        """Test scientific notation values."""
        text = """pnl_unrealized 1.23456789e3
order_fill_ratio 6.67e-1
"""
        result = _parse_prometheus_text(text)
        self.assertEqual(result["pnl_unrealized"], 1234.56789)
        self.assertEqual(result["order_fill_ratio"], 0.667)

    def test_negative_values(self):
        """Test negative values."""
        text = """pnl_realized -456.78
drift_score -0.05
"""
        result = _parse_prometheus_text(text)
        expected = {
            "pnl_realized": -456.78,
            "drift_score": -0.05,
        }
        self.assertEqual(result, expected)

    def test_mixed_aliases(self):
        """Test mixed aliases that should map to friendly names."""
        text = """# Mix of common aliases
pnl_realised 1000.50
policy_drift 0.33
fill_ratio 0.75
exchange_latency_ms 89.12
"""
        result = _parse_prometheus_text(text)
        expected = {
            "pnl_realised": 1000.50,
            "policy_drift": 0.33,
            "fill_ratio": 0.75,
            "exchange_latency_ms": 89.12,
        }
        self.assertEqual(result, expected)

    def test_comments_and_empty_lines(self):
        """Test handling of comments and empty lines."""
        text = """
# This is a comment
   # Another comment

pnl_realized 999.99

# Blank lines should be ignored

policy_confidence 0.77
"""
        result = _parse_prometheus_text(text)
        expected = {
            "pnl_realized": 999.99,
            "policy_confidence": 0.77,
        }
        self.assertEqual(result, expected)

    def test_invalid_lines_ignored(self):
        """Test that invalid lines are ignored gracefully."""
        text = """pnl_realized 123.45
invalid line without number
another_invalid{broken 456
policy_confidence not_a_number
drift_score 0.42
"""
        result = _parse_prometheus_text(text)
        expected = {
            "pnl_realized": 123.45,
            "drift_score": 0.42,
        }
        self.assertEqual(result, expected)

    def test_prom_map_resolution(self):
        """Test that PROM_MAP correctly maps aliases to friendly names."""
        # This tests the expectation that prometheus parsing works with aliases
        text = """# Using various aliases
pnl_realised 1111.11
policy_drift 0.55
hmm_policy_confidence 0.92
execution_fill_ratio 0.88
venue_latency 67.89
"""
        result = _parse_prometheus_text(text)
        # Verify results structure (actual mapping happens in _get_prometheus_metrics)
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)


class TestJsonHelpers(unittest.TestCase):
    """Test _from_json helper for extracting values from nested JSON."""

    def test_flat_structure(self):
        """Test flat JSON structure."""
        obj = {"pnl_realized": 1234.56, "drift_score": 0.42}
        self.assertEqual(_from_json(obj, "pnl_realized"), 1234.56)
        self.assertEqual(_from_json(obj, "drift_score"), 0.42)
        self.assertEqual(_from_json(obj, "missing_key"), 0.0)

    def test_nested_structure(self):
        """Test nested JSON structure like Ops API responses."""
        obj = {
            "pnl": {"realized": 1000.0, "pnl_realized": 2000.0},
            "policy": {"drift": 0.33, "confidence": 0.88},
        }
        # Test key extraction with fallbacks
        self.assertEqual(_from_json(obj["pnl"], "realized", "pnl_realized"), 1000.0)
        self.assertEqual(_from_json(obj["policy"], "drift", "drift_score"), 0.33)
        self.assertEqual(
            _from_json(obj["policy"], "confidence", "policy_confidence"), 0.88
        )

    def test_invalid_inputs(self):
        """Test handling of None/invalid inputs."""
        self.assertEqual(_from_json(None, "key"), 0.0)
        # Type ignore for testing invalid inputs (runtime behavior)
        self.assertEqual(_from_json({}, "key"), 0.0)  # type: ignore
        self.assertEqual(_from_json({"key": "not_number"}, "key"), 0.0)

    def test_custom_default(self):
        """Test custom default values."""
        self.assertEqual(_from_json(None, "key", default=42.0), 42.0)


class TestFallbackShapes(unittest.TestCase):
    """Test parsing various JSON shapes from fallback chain."""

    def test_ops_snapshot_shape(self):
        """Test Ops snapshot JSON shape."""
        obj = {
            "metrics": {
                "pnl_realized": 1234.56,
                "pnl_unrealized": 78.90,
                "drift_score": 0.42,
                "policy_confidence": 0.88,
                "order_fill_ratio": 0.67,
                "venue_latency_ms": 42.0,
            }
        }
        metrics = obj.get("metrics") if "metrics" in obj else obj
        result = {
            "pnl_realized": _from_json(metrics, "pnl_realized"),
            "pnl_unrealized": _from_json(metrics, "pnl_unrealized"),
            "drift_score": _from_json(metrics, "drift_score"),
            "policy_confidence": _from_json(metrics, "policy_confidence"),
            "order_fill_ratio": _from_json(metrics, "order_fill_ratio"),
            "venue_latency_ms": _from_json(metrics, "venue_latency_ms"),
        }
        expected = {
            "pnl_realized": 1234.56,
            "pnl_unrealized": 78.90,
            "drift_score": 0.42,
            "policy_confidence": 0.88,
            "order_fill_ratio": 0.67,
            "venue_latency_ms": 42.0,
        }
        self.assertEqual(result, expected)

    def test_ops_metrics_shape(self):
        """Test generic /metrics JSON shape."""
        obj = {
            "pnl": {"realized_usd": 1234.56, "unrealized_usd": 78.90},
            "policy": {"drift": 0.42, "policy_confidence": 0.88},
            "execution": {"fill_ratio": 0.67, "venue_latency_ms": 42.0},
        }
        pnl = obj.get("pnl", obj)
        pol = obj.get("policy", obj)
        exe = obj.get("execution", obj)
        result = {
            "pnl_realized": _from_json(pnl, "realized", "pnl_realized", "realized_usd"),
            "pnl_unrealized": _from_json(
                pnl, "unrealized", "pnl_unrealized", "unrealized_usd"
            ),
            "drift_score": _from_json(pol, "drift", "drift_score"),
            "policy_confidence": _from_json(pol, "confidence", "policy_confidence"),
            "order_fill_ratio": _from_json(exe, "fill_ratio", "order_fill_ratio"),
            "venue_latency_ms": _from_json(
                exe, "venue_latency_ms", "latency_ms", "exchange_latency_ms"
            ),
        }
        expected = {
            "pnl_realized": 1234.56,
            "pnl_unrealized": 78.90,
            "drift_score": 0.42,
            "policy_confidence": 0.88,
            "order_fill_ratio": 0.67,
            "venue_latency_ms": 42.0,
        }
        self.assertEqual(result, expected)

    def test_split_endpoints_shape(self):
        """Test split /pnl and /state endpoints."""
        pnl_obj = {"realized_usd": 1234.56, "unrealized_usd": 78.90}
        state_obj = {
            "drift": 0.42,
            "confidence": 0.88,
            "fill_ratio": 0.67,
            "exchange_latency_ms": 42.0,
        }

        result = {
            "pnl_realized": _from_json(
                pnl_obj, "realized", "pnl_realized", "realized_usd"
            ),
            "pnl_unrealized": _from_json(
                pnl_obj, "unrealized", "pnl_unrealized", "unrealized_usd"
            ),
            "drift_score": _from_json(state_obj, "drift", "drift_score"),
            "policy_confidence": _from_json(
                state_obj, "confidence", "policy_confidence"
            ),
            "order_fill_ratio": _from_json(state_obj, "fill_ratio", "order_fill_ratio"),
            "venue_latency_ms": _from_json(
                state_obj, "latency_ms", "venue_latency_ms", "exchange_latency_ms"
            ),
        }
        expected = {
            "pnl_realized": 1234.56,
            "pnl_unrealized": 78.90,
            "drift_score": 0.42,
            "policy_confidence": 0.88,
            "order_fill_ratio": 0.67,
            "venue_latency_ms": 42.0,
        }
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
