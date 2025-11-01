import os
import logging
import pytest

from engine.core.order_router import OrderRouterExt, set_exchange_client
from engine.core.portfolio import Portfolio


class _MockClient:
    def __init__(self, last=100.0, avg=101.0):
        self._last = last
        self._avg = avg

    def get_last_price(self, symbol: str):
        return self._last

    async def submit_market_order(self, symbol: str, side: str, quantity: float):
        return {
            "executedQty": quantity,
            "avg_fill_price": self._avg,
            "filled_qty_base": quantity,
            "status": "FILLED",
        }


@pytest.mark.asyncio
async def test_slippage_warn_logged(caplog, monkeypatch):
    caplog.set_level(logging.WARNING)
    os.environ["BINANCE_MODE"] = "futures_testnet"
    os.environ["FUT_TAKER_MAX_SLIP_BPS"] = "15"

    client = _MockClient(last=100.0, avg=101.0)
    set_exchange_client("BINANCE", client)
    router = OrderRouterExt(client, Portfolio(), venue="BINANCE")

    await router.place_entry(
        "BTCUSDT.BINANCE", "BUY", 0.01, venue="BINANCE", intent="SCALP"
    )
    assert any("SLIPPAGE" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_scalp_maker_shadow_logs(caplog):
    caplog.set_level(logging.INFO)
    os.environ["SCALP_MAKER_SHADOW"] = "true"
    client = _MockClient(last=100.0, avg=100.0)
    set_exchange_client("BINANCE", client)
    router = OrderRouterExt(client, Portfolio(), venue="BINANCE")

    await router.place_entry(
        "ETHUSDT.BINANCE", "BUY", 0.1, venue="BINANCE", intent="SCALP"
    )
    assert any("SCALP:MAKER:SHADOW" in rec.message for rec in caplog.records)
