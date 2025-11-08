import pytest

from engine.dex.config import DexConfig
from engine.dex.executor import DexExecutionResult
from engine.dex.state import DexState
from engine.strategies.dex_sniper import DexSniper


class StubExecutor:
    def __init__(self):
        self.calls = []

    async def buy(
        self, *, symbol: str, token_address: str, notional_usd: float
    ) -> DexExecutionResult:
        self.calls.append((symbol, token_address, notional_usd))
        price = 0.001
        qty = notional_usd / price
        return DexExecutionResult(
            symbol=symbol, qty=qty, price=price, notional=notional_usd, side="BUY"
        )


def _mk_cfg(tmp_path, *, exec_enabled=True):
    return DexConfig(
        feed_enabled=True,
        exec_enabled=exec_enabled,
        watcher_enabled=False,
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
        chain_whitelist=("ETH", "BSC"),
        rpc_url="http://localhost:8545",
        chain_id=1,
        router_address="0x0000000000000000000000000000000000000001",
        stable_token="0x0000000000000000000000000000000000000002",
        wrapped_native_token="0x0000000000000000000000000000000000000003",
        wallet_private_key="0x" + "1" * 64,
        max_gas_price_wei=1,
        gas_limit=100000,
        price_oracle="dexscreener",
        watcher_poll_sec=5.0,
    )


@pytest.mark.asyncio
async def test_dex_sniper_exec_opens_position(tmp_path):
    cfg = _mk_cfg(tmp_path)
    state = DexState(cfg.state_path)
    executor = StubExecutor()
    sniper = DexSniper(cfg, state, executor)

    payload = {
        "symbol": "PEPE",
        "chain": "ETH",
        "addr": "0x123",
        "tier": "A",
        "price": 0.001,
        "liq": 300_000.0,
        "mcap": 4_000_000.0,
        "holders": 1500,
    }

    handled = await sniper.handle_candidate(payload)
    assert handled is True
    assert len(executor.calls) == 1
    assert state.count_open() == 1
    pos = state.open_positions()[0]
    assert pos.symbol == "PEPE"
    assert pos.notional == pytest.approx(50.0)
    assert pos.stop_loss_pct == pytest.approx(0.12)
    assert len(pos.tp_targets) == 2


@pytest.mark.asyncio
async def test_dex_sniper_respects_limits(tmp_path):
    cfg = _mk_cfg(tmp_path)
    state = DexState(cfg.state_path)
    executor = StubExecutor()
    sniper = DexSniper(cfg, state, executor)

    payload = {
        "symbol": "DOGEAI",
        "chain": "ETH",
        "addr": "0x321",
        "tier": "B",
        "price": 0.01,
        "liq": 250_000.0,
        "mcap": 7_000_000.0,
    }

    assert await sniper.handle_candidate(payload) is True
    # Second attempt should be skipped because max_live_positions=1 and symbol already open
    assert await sniper.handle_candidate(payload) is False
    assert state.count_open() == 1
