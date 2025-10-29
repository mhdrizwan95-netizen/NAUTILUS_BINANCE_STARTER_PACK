# Telemetry Contracts (FastAPI → WebSocket → UI)

## Strategy Pod Update
```json
{
  "type": "pod_update",
  "strategy": "HMM",
  "venue": "Binance Futures",
  "pnl_pct": 2.43,
  "confidence": 0.78,
  "latency_ms": 28,
  "var_pct": 1.6,
  "hit_rate": 62,
  "symbols": ["BTC", "SOL", "ETH"],
  "status": "ok" // ok|cooldown|error
}
```

## System Snapshot
```json
{
  "type": "system_snapshot",
  "equity": 2045.12,
  "total_pnl": 123.45,
  "daily_pnl_pct": 1.23,
  "sharpe": 1.8,
  "max_drawdown_pct": 6.4,
  "latency_ms_p95": 33,
  "signal_per_min": 4.2,
  "venues_enabled": {"Spot": true, "Margin": true, "Futures": true, "Options": false},
  "trading_enabled": true,
  "mode": "Paper"
}
```

## Trade Event
```json
{
  "type": "trade",
  "ts": "2025-01-01T12:34:56Z",
  "strategy": "Trend",
  "symbol": "BTCUSDT",
  "side": "BUY",
  "qty": 0.01,
  "px": 30000.0,
  "venue": "Futures",
  "pnl_realized": 25.4
}
```
