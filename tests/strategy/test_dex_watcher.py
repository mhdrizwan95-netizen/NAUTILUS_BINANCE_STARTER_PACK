import pytest

from engine.dex.config import DexConfig
from engine.dex.executor import DexExecutionResult
from engine.dex.state import DexState
from engine.dex.watcher import DexWatcher


class StubExecutor:
    def __init__(self):
        self.calls = []

    async def sell(self, *, symbol: str, token_address: str, qty: float):
        self.calls.append((symbol, token_address, qty))
        return DexExecutionResult(symbol=symbol, qty=qty, price=0.02, notional=qty * 0.02, side="SELL")


class StubOracle:
    def __init__(self, price):
        self.price = price

    async def price_usd(self, token_identifier: str):
        return self.price

    async def close(self):
        return None


def _cfg(tmp_path):
    return DexConfig(
        feed_enabled=True,
        exec_enabled=True,
        watcher_enabled=True,
        max_live_positions=1,
        size_tier_a=50.0,
        size_tier_b=25.0,
        stop_loss_pct=0.12,
        tp1_pct=0.20,
        tp1_portion=0.40,
        tp2_pct=0.40,
        tp2_portion=0.30,
        trail_pct=0.10,
        slippage_bps=80.0,
        max_slippage_bps=120.0,
        tax_max_pct=5.0,
        min_liq_usd=200_000.0,
        max_top10_pct=70.0,
        state_path=str(tmp_path / "dex_positions.json"),
        chain_whitelist=("ETH",),
        rpc_url="http://localhost:8545",
        chain_id=1,
        router_address="0x0000000000000000000000000000000000000001",
        stable_token="0x0000000000000000000000000000000000000002",
        wrapped_native_token="0x0000000000000000000000000000000000000003",
        wallet_private_key="0x" + "2" * 64,
        max_gas_price_wei=1,
        gas_limit=100000,
        price_oracle="dexscreener",
        watcher_poll_sec=1.0,
    )


@pytest.mark.asyncio
async def test_watcher_triggers_take_profit(tmp_path):
    cfg = _cfg(tmp_path)
    state = DexState(cfg.state_path)
    executor = StubExecutor()
    oracle = StubOracle(price=0.02)  # double entry → should hit first TP
    watcher = DexWatcher(cfg, state, executor, oracle)

    pos = state.open_position(
        symbol="PEPE",
        chain="ETH",
        address="0xabc",
        tier="A",
        qty=1000.0,
        entry_price=0.01,
        notional=10.0,
        stop_loss_pct=cfg.stop_loss_pct,
        trail_pct=cfg.trail_pct,
        metadata={"initial_qty": 1000.0, "high_price": 0.01},
        targets=cfg.tp_targets,
    )

    await watcher.tick()
    assert executor.calls, "expected sell call"
    assert pos.tp_targets[0].filled is True
    state_pos = state.refresh_position(pos.pos_id)
    assert state_pos.qty < 1000.0
