import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

from engine.core.binance_user_stream import BinanceUserStream
from engine.core.portfolio import Portfolio
from engine.services.telemetry_broadcaster import BROADCASTER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_telemetry")

async def test_telemetry_flow():
    logger.info("--- Testing Telemetry Flow ---")

    # 1. Setup Portfolio & Broadcaster
    received_payloads = []
    
    def on_portfolio_update(snapshot):
        logger.info(f"Portfolio Update: Equity={snapshot.get('equity')}")
        asyncio.create_task(BROADCASTER.broadcast({"type": "account_update", "data": snapshot}))

    portfolio = Portfolio(starting_cash=10000.0, on_update=on_portfolio_update)
    
    # Subscribe to Broadcaster
    queue = await BROADCASTER.subscribe()
    
    async def listener():
        while True:
            payload = await queue.get()
            received_payloads.append(payload)
            logger.info(f"Received Broadcast: {payload.get('type')}")

    listener_task = asyncio.create_task(listener())

    # 2. Setup BinanceUserStream with Mocks
    mock_ws = AsyncMock()
    mock_ws.__aenter__.return_value = mock_ws
    
    # Mock Messages
    account_update = {
        "e": "ACCOUNT_UPDATE",
        "a": {
            "B": [
                {"a": "USDT", "wb": "10500.0", "cw": "10500.0"}
            ]
        }
    }
    
    order_update = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": "BTCUSDT",
            "S": "BUY",
            "X": "FILLED",
            "L": "50000.0",
            "l": "0.1",
            "n": "1.0",
            "N": "USDT"
        }
    }
    
    async def async_iter():
        for msg in [json.dumps(account_update), json.dumps(order_update)]:
            yield msg
            
    mock_ws.__aiter__.side_effect = async_iter

    # Callbacks
    async def on_account_update(data):
        logger.info("Callback: Account Update")
        balances = {}
        for bal in data.get("a", {}).get("B", []):
            balances[bal.get("a")] = float(bal.get("wb", 0.0))
        portfolio.sync_wallet(balances)

    async def on_order_update(data):
        logger.info("Callback: Order Update")
        o = data.get("o", {})
        portfolio.apply_fill(
            symbol=o.get("s"),
            side=o.get("S"),
            quantity=float(o.get("l", 0.0)),
            price=float(o.get("L", 0.0)),
            fee_usd=float(o.get("n", 0.0)),
            venue="BINANCE"
        )

    stream = BinanceUserStream(
        on_account_update=on_account_update,
        on_order_update=on_order_update
    )
    
    # Patch httpx and websockets
    with patch("httpx.AsyncClient") as mock_client, \
         patch("websockets.connect", return_value=mock_ws):
        
        mock_client_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.post.return_value.json.return_value = {"listenKey": "test_key"}
        mock_client_instance.post.return_value.raise_for_status = MagicMock()

        # Run stream for a short time
        task = asyncio.create_task(stream.run())
        await asyncio.sleep(1)
        stream._stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            pass

    # 3. Verify
    logger.info(f"Received Payloads: {len(received_payloads)}")
    
    # Verify Wallet Sync
    assert portfolio.state.cash == 10500.0, f"Cash mismatch: {portfolio.state.cash}"
    logger.info("✅ Wallet Sync Verified")

    # Verify Fill
    pos = portfolio.state.positions.get("BTCUSDT")
    assert pos is not None, "Position not found"
    assert pos.quantity == 0.1, f"Qty mismatch: {pos.quantity}"
    logger.info("✅ Order Fill Verified")

    # Verify Broadcast
    assert len(received_payloads) >= 2, "Broadcasts missing"
    logger.info("✅ Broadcast Verified")

    listener_task.cancel()

if __name__ == "__main__":
    asyncio.run(test_telemetry_flow())
