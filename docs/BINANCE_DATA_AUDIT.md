# Binance Data Integration Audit

## 1. Data Sources Overview

The system handles Binance data through three distinct channels:

### A. Historical Data (Training)
- **Service**: `services/data_ingester`
- **Method**: Polling via `ccxt` library
- **Format**: Downloads OHLCV candles to `/ml/incoming` (CSV)
- **Status**: ✅ **Implemented** (but currently empty on disk)

### B. Live Execution Data (Private)
- **Component**: `engine/core/binance_user_stream.py`
- **Method**: WebSocket (`wss://stream.binance.com:9443/ws/...`)
- **Data**: Order updates, Fills, Account balances
- **Status**: ✅ **Implemented** (Standard User Data Stream)

### C. Live Market Data (Public)
- **Component**: `engine/core/binance.py` (REST) & `engine/feeds/market_data_dispatcher.py`
- **Method**: **Polling** via REST API (`ticker_price`)
- **Gap Identified**: ⚠️ **No Public WebSocket Stream**
  - The system does **not** connect to `wss://stream.binance.com/ws/@aggTrade` or `@bookTicker`.
  - Strategies rely on polled prices (slower) or internal mark price updates which are currently not driven by a high-frequency source.
  - `MarketDataDispatcher` exists but has no external driver pushing public ticks to it.

## 2. Recommendations

1.  **Implement `BinanceMarketStream`**: Create a new connector in `engine/feeds` to subscribe to Binance Public WebSocket channels.
2.  **Wire to Dispatcher**: Feed these WS events into `MarketDataDispatcher.handle_stream_event()`.
3.  **Run Ingester**: Build the historical dataset by running the `ingest_once` endpoint.
