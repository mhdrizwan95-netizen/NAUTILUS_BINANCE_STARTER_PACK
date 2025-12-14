
import asyncio
import logging
import os
import signal
import sys
from decimal import Decimal

from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId

# Components
from engine.config.node_config import get_node_config
from engine.strategies.nautilus_trend import NautilusTrendStrategy, NautilusTrendConfig
from engine.actors.bridge_actor import BridgeActor
from engine.actors.strategy_supervisor import StrategySupervisor
from engine.inference.async_engine import AsyncInferenceEngine
from engine.core.event_bus import initialize_event_bus

# Health Shim
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/health', '/readyz'):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "mode": "neuro-symbolic-phase7"}')
        else:
            self.send_response(404)

def start_health_server():
    server = HTTPServer(('0.0.0.0', 8003), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("NeuroSymbolicNode")
    
    # 0. Phase 7 Validation
    if not os.getenv("BINANCE_API_KEY") and not os.getenv("simulation_mode"):
        logger.warning("⚠️  BINANCE_API_KEY not found in env. Ensure .env is loaded.")
        # We allow proceeding for verification purposes if sim mode
    
    logger.info("🚀 Neuro-Symbolic Engine Starting... Bridge Connected.")
    
    # 1. Start Health
    start_health_server()
    
    # 2. Node
    node_config = get_node_config("BINANCE", "BTCUSDT", log_level="INFO")
    node = TradingNode(config=node_config)
    
    # 3. Components
    inference_engine = AsyncInferenceEngine(max_workers=2)
    bridge = BridgeActor(message_bus=node.message_bus)
    supervisor = StrategySupervisor(
        message_bus=node.message_bus,
        trader=node.trader,
        inference_engine=inference_engine
    )
    
    # 4. Registration
    node.add_actor(bridge)
    node.add_actor(supervisor)
    
    # Factories
    from nautilus_trader.adapters.binance.factories import BinanceLiveDataClientFactory, BinanceLiveExecClientFactory
    node.add_data_client_factory("BINANCE", BinanceLiveDataClientFactory)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)

    # 5. Build
    node.build()
    
    try:
        # Start Legacy Bus
        loop = node.loop
        loop.create_task(initialize_event_bus())
        
        node.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        inference_engine.shutdown()

if __name__ == "__main__":
    main()
