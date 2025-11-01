import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def test_backtest_stub_absent():
    assert not exists("run_backtest.py"), "run_backtest.py should be removed"
    assert not exists("ops/run_backtest.py"), "ops/run_backtest.py should be removed"
    assert not exists(
        "scripts/run_backtest.py"
    ), "scripts/run_backtest.py should be removed"


def test_engine_imports_ok():
    for mod in [
        "engine.app",
        "engine.strategies.policy_hmm",
        "engine.strategies.ensemble_policy",
    ]:
        spec = importlib.util.find_spec(mod)
        assert spec is not None, f"Missing required module: {mod}"
