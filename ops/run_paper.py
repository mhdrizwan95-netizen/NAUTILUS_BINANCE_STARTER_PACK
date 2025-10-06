# M1: run_paper.py (Binance Spot testnet)
import asyncio
import os
from dotenv import load_dotenv
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.live.data_engine import LiveDataEngine
from nautilus_trader.live.execution_engine import LiveExecutionEngine
from nautilus_trader.adapters.binance.spot.http.client import BinanceSpotHttpClient
from nautilus_trader.adapters.binance.spot.data import BinanceSpotDataClient
from nautilus_trader.adapters.binance.spot.execution import BinanceSpotExecutionClient
from nautilus_trader.config import DataEngineConfig, ExecEngineConfig
from nautilus_trader.core import Clock, MessageBus, Cache
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.model.instruments import CryptoSpot
from nautilus_trader.model.currencies import BTC, USDT
from strategies.hmm_policy.config import HMMPolicyConfig
from strategies.hmm_policy.strategy import HMMPolicyStrategy

async def main():
    load_dotenv()
    symbol = os.getenv("SYMBOL", "BTCUSDT.BINANCE")
    print(f"[M1] Starting paper engine for {symbol} on Binance Spot Testnet")

    # Create core components
    clock = Clock()
    msgbus = MessageBus(
        trader_id="HMM-TRADER-001",
        clock=clock,
        message_stale_ms=10000,
    )
    cache = Cache()
    portfolio = Portfolio(
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )

    # Configure clients
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    testnet = os.getenv("BINANCE_IS_TESTNET", "true").lower() == "true"

    http_client = BinanceSpotHttpClient(
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
        loop=asyncio.get_event_loop(),
    )

    data_client = BinanceSpotDataClient(
        client=http_client,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )

    exec_client = BinanceSpotExecutionClient(
        client=http_client,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )

    # Create engine configs
    data_config = DataEngineConfig()
    exec_config = ExecEngineConfig()

    # Create engines
    data_engine = LiveDataEngine(
        loop=asyncio.get_event_loop(),
        config=data_config,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )

    exec_engine = LiveExecutionEngine(
        loop=asyncio.get_event_loop(),
        config=exec_config,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        portfolio=portfolio,
    )

    # Add clients to engines
    data_engine.add_client(data_client)
    exec_engine.add_client(exec_client)

    # Start HTTP client and engines
    await http_client.connect()
    await data_engine.start()
    await exec_engine.start()

    # Load instrument (BTC/USDT spot)
    bitcoin = BTC()
    usd_tether = USDT()
    instrument = CryptoSpot(
        id=InstrumentId(symbol="BTCUSDT", venue=Venue("BINANCE")),
        base_currency=bitcoin,
        quote_currency=usd_tether,
        price_precision=2,
        size_precision=6,
        fee_currency=usd_tether,
        maker_fee=0.001,
        taker_fee=0.001,
        ts_event_ns=0,
        ts_init_ns=0,
        max_quantity=9000,
        min_quantity=0.000001,
        max_price=1000000,
        min_price=0.01,
    )
    cache.add_instrument(instrument)
    instrument_id = instrument.id

    # Config and strategy
    cfg = HMMPolicyConfig.from_env()
    strategy = HMMPolicyStrategy(config=cfg)

    # Subscribe to data
    _ = await data_client.subscribe_order_book_deltas(instrument_id=instrument_id, depth=20)
    _ = await data_client.subscribe_trade_ticks(instrument_id=instrument_id)

    # Run event loop (keep alive)
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        await exec_engine.stop()
        await data_engine.stop()
        await http_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
