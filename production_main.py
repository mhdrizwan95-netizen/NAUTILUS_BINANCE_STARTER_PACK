
import logging
from nautilus_trader.live.node import TradingNode
from nautilus_trader.adapters.binance.factories import BinanceLiveDataClientFactory, BinanceLiveExecClientFactory

from engine.config.node_config import get_node_config, get_binance_config
from engine.strategies.nautilus_trend import NautilusTrendStrategy, NautilusTrendConfig

def main():
    # 1. Load Hardened Config
    data_config, exec_config = get_binance_config()
    node_config = get_node_config(data_config, exec_config)
    
    # 2. Initialize Node
    node = TradingNode(config=node_config)
    
    # 3. Add Binance Adapters (Fixing V-01 Ghost Framework)
    # Using the Factories to correctly register the adapter actors
    node.add_data_client_factory("BINANCE", BinanceLiveDataClientFactory)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    
    # 4. Configure Strategy
    stop_loss_mult = 2.0
    strat_config = NautilusTrendConfig(
        symbol="BTCUSDT-PERP.BINANCE",
        bar_type="BTCUSDT-PERP.BINANCE-1m-MID", 
        # Tuning parameters can be loaded here
        sma_fast=10,
        sma_slow=20
    )
    
    strategy = NautilusTrendStrategy(strat_config)
    node.trader.add_strategy(strategy)
    
    # 5. Run
    node.build()
    print("🚀 Operation Nautilus: Starting Production Node...")
    # This will block until stopped
    node.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # [API SHIM] Start a minimal health-check server for Docker/K8s
    # This ensures the container doesn't get killed while the proper Nautilus engine runs.
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health" or self.path == "/readyz":
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok", "engine": "nautilus"}')
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, format, *args):
            pass # Silence logs

    def run_server():
        logging.info("🏥 Starting API Health Shim on port 8003...")
        server = HTTPServer(("0.0.0.0", 8003), HealthHandler)
        server.serve_forever()

    shim_thread = threading.Thread(target=run_server, daemon=True)
    shim_thread.start()

    main()
