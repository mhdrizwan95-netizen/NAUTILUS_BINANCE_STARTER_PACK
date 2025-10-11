import json, os, pytest, asyncio
from pathlib import Path
import respx
from httpx import Response
from fastapi.testclient import TestClient
from ops.strategy_tracker import strategy_tracker_loop, load_registry, save_registry
from ops.strategy_selector import promote_best, rank_strategies, get_leaderboard
from ops.strategy_selector import push_model_update

@pytest.fixture(autouse=True)
def _registry_reset(tmp_path):
    """Reset registry file before each test."""
    global TEST_REGISTRY_PATH
    TEST_REGISTRY_PATH = tmp_path / "strategy_registry.json"

    # Monkey patch the global registry path for testing
    import ops.strategy_tracker as tracker_mod
    import ops.strategy_selector as selector_mod

    original_path = tracker_mod.REGISTRY_PATH
    tracker_mod.REGISTRY_PATH = TEST_REGISTRY_PATH
    selector_mod.REGISTRY_PATH = TEST_REGISTRY_PATH

    # Start with clean registry
    registry_path = TEST_REGISTRY_PATH
    registry_path.write_text(json.dumps({"current_model": "hmm_v1"}))

    yield

    # Restore original path
    tracker_mod.REGISTRY_PATH = original_path
    selector_mod.REGISTRY_PATH = original_path

@pytest.fixture
def sample_registry():
    return {
        "hmm_v1": {
            "sharpe": 0.92,
            "drawdown": 4.1,
            "realized": 134.2,
            "trades": 284,
            "last_pnl": 12.5,
            "samples": [10.2, 15.1, 8.9]
        },
        "ma_crossover_v3": {
            "sharpe": 1.17,
            "drawdown": 3.3,
            "realized": 185.7,
            "trades": 310,
            "last_pnl": -8.3,
            "samples": [22.1, 18.7, 15.9]
        },
        "ensemble_v2": {
            "sharpe": 1.04,
            "drawdown": 2.7,
            "realized": 162.0,
            "trades": 298,
            "last_pnl": 25.4,
            "samples": [20.5, 18.2, 22.1]
        },
        "current_model": "hmm_v1"
    }

def test_registry_load_save(sample_registry):
    """Test registry persistence operations."""
    save_registry(sample_registry)
    loaded = load_registry()

    assert loaded["current_model"] == "hmm_v1"
    assert loaded["hmm_v1"]["sharpe"] == 0.92
    assert loaded["ma_crossover_v3"]["trades"] == 310

def test_strategy_ranking(sample_registry):
    """Test strategy ranking logic."""
    ranked = rank_strategies(sample_registry)

    assert len(ranked) == 3
    # ma_crossover_v3 should rank first (highest Sharpe)
    assert ranked[0][0] == "ma_crossover_v3"
    assert ranked[0][1] > ranked[1][1]  # Higher score than second
    # ensemble_v2 second, hmm_v1 third

def test_promote_best(sample_registry):
    """Test promotion of best performing strategy."""
    save_registry(sample_registry)

    # Initially hmm_v1 is current
    assert load_registry()["current_model"] == "hmm_v1"

    promote_best()

    # Should promote ma_crossover_v3 (best Sharpe ratio)
    updated = load_registry()
    assert updated["current_model"] == "ma_crossover_v3"

def test_promote_no_op(sample_registry):
    """Test no promotion when already running best model."""
    sample_registry["current_model"] = "ma_crossover_v3"
    save_registry(sample_registry)

    promote_best()

    # Should stay ma_crossover_v3
    updated = load_registry()
    assert updated["current_model"] == "ma_crossover_v3"

def test_get_leaderboard(sample_registry):
    """Test leaderboard generation."""
    save_registry(sample_registry)

    board = get_leaderboard()

    assert len(board) == 3
    assert board[0]["name"] == "ma_crossover_v3"
    assert board[0]["rank"] == 1
    assert board[0]["is_current"] is False  # hmm_v1 is current
    assert board[1]["name"] == "ensemble_v2"
    assert board[2]["name"] == "hmm_v1"
    assert board[2]["is_current"] is True

@pytest.mark.asyncio
async def test_strategy_tracker_metrics_collection(monkeypatch, sample_registry):
    """Test collection of strategy performance metrics from engine endpoints."""
    sample_registry["current_model"] = "hmm_v1"
    save_registry(sample_registry)

    # Mock engine responses with model-tagged metrics
    metrics_response = """# HELP pnl_realized_total Realized PnL by model
# TYPE pnl_realized_total gauge
pnl_realized_total{model="hmm_v1",venue="BINANCE"} 134.2
pnl_unrealized_total{model="hmm_v1",venue="BINANCE"} 12.5
pnl_realized_total{model="ma_crossover_v3",venue="BINANCE"} 185.7
pnl_unrealized_total{model="ma_crossover_v3",venue="BINANCE"} -8.3
"""

    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://engine_binance:8003")

    with respx.mock:
        respx.get("http://engine_binance:8003/metrics").mock(return_value=Response(200, text=metrics_response))

        # Run tracker once (cancel after iteration)
        task = asyncio.create_task(strategy_tracker_loop())
        await asyncio.sleep(1.5)  # Let one iteration run
        task.cancel()

    # Check that registry was updated with new metrics
    updated = load_registry()
    assert updated["hmm_v1"]["realized"] == 134.2
    assert updated["hmm_v1"]["last_pnl"] == 146.7  # 134.2 + 12.5
    assert updated["ma_crossover_v3"]["realized"] == 185.7
    assert updated["ma_crossover_v3"]["last_pnl"] == 177.4  # 185.7 - 8.3

def test_strategy_governance_api_endpoints(monkeypatch):
    """Test governance API endpoints."""
    import ops.ops_api as ops_app

    # Mock registry
    sample_reg = {
        "hmm_v1": {"sharpe": 0.92, "drawdown": 4.1, "realized": 134.2, "trades": 284, "samples": []},
        "ma_crossover_v3": {"sharpe": 1.17, "drawdown": 3.3, "realized": 185.7, "trades": 310, "samples": []},
        "current_model": "hmm_v1"
    }
    save_registry(sample_reg)

    client = TestClient(ops_app.app)

    # Test status endpoint
    response = client.get("/strategy/status")
    assert response.status_code == 200
    data = response.json()

    assert "registry" in data
    assert "leaderboard" in data
    assert data["registry"]["current_model"] == "hmm_v1"
    assert len(data["leaderboard"]) == 2  # Strategies with sufficient data

@pytest.mark.asyncio
async def test_push_model_update(monkeypatch):
    """Test broadcasting strategy changes to engines."""
    monkeypatch.setenv("ENGINE_ENDPOINTS", "http://engine_binance:8003,http://engine_ibkr:8005")

    with respx.mock:
        # Mock successful responses from engines
        respx.post("http://engine_binance:8003/strategy/promote").mock(return_value=Response(200, json={"status": "ok"}))
        respx.post("http://engine_ibkr:8005/strategy/promote").mock(return_value=Response(200, json={"status": "ok"}))

        await push_model_update("ensemble_v2")

        # Verify both engines received the update
        assert respx.requests[0].url.path == "/strategy/promote"
        assert respx.requests[1].url.path == "/strategy/promote"

def test_strategy_promotion_with_minimum_trades(sample_registry):
    """Test that strategies require minimum trading history to promote."""
    # Add a new strategy with insufficient history
    sample_registry["new_strategy"] = {
        "sharpe": 2.0,  # Great Sharpe but...
        "drawdown": 1.0,
        "realized": 50.0,
        "trades": 1,    # Only 1 trade!
        "last_pnl": 10.0,
        "samples": [10.0]
    }
    save_registry(sample_registry)

    ranked = rank_strategies(sample_registry)

    # New strategy should not appear in top rankings due to insufficient data
    strategy_names = [name for name, score, stats in ranked]
    assert "new_strategy" not in strategy_names

def test_manual_promotion_override():
    """Test manual promotion API with auth."""
    import ops.ops_api as ops_app
    from fastapi.testclient import TestClient

    # Mock registry
    initial_reg = {
        "current_model": "hmm_v1",
        "hmm_v1": {"manual": False},
        "ensemble_v2": {"manual": False}
    }
    save_registry(initial_reg)

    # Set auth token for test
    os.environ["OPS_API_TOKEN"] = "dev-token"

    client = TestClient(ops_app.app)

    # Manual promotion request
    response = client.post(
        "/strategy/promote",
        json={"model_tag": "ensemble_v2"},
        headers={"X-OPS-TOKEN": "dev-token"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["promoted"] == "ensemble_v2"
    assert data["ok"] is True

    # Verify registry updated
    updated = load_registry()
    assert updated["current_model"] == "ensemble_v2"

def test_strategy_drawdown_penalty():
    """Test that drawdown penalizes the ranking score."""
    registry = {
        "high_sharpe_low_dd": {
            "sharpe": 1.5,
            "drawdown": 2.0,
            "realized": 100.0,
            "trades": 10,
            "samples": [10, 11, 12],
            "last_pnl": 10.5
        },
        "higher_sharpe_high_dd": {
            "sharpe": 1.8,
            "drawdown": 5.0,  # Higher drawdown should drag score down
            "realized": 100.0,
            "trades": 10,
            "samples": [10, 11, 12],
            "last_pnl": 10.5
        },
        "current_model": None
    }

    ranked = rank_strategies(registry)

    # Despite higher Sharpe, high DD strategy should rank second
    assert len(ranked) == 2
    assert ranked[0][0] == "high_sharpe_low_dd"  # Better due to lower drawdown
    assert ranked[1][0] == "higher_sharpe_high_dd"
