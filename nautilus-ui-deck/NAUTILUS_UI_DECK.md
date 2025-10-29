# NAUTILUS Trading Command Center — UI Deck

This deck contains:
- **Design tokens** (`design/nautilus.tokens.json`)
- **Telemetry contracts** (`docs/telemetry-contracts.md`)
- **Standalone example app** (`examples/nautilus-dashboard`) — Next.js + Tailwind + Zustand prototype of the cockpit

## What’s implemented in the example
- **Top HUD** (trading toggle, mode toggle, venue filters, NAV/PnL/Sharpe/DD, latency p95)
- **Strategy Matrix** (pods for HMM, MeanRev, Breakout, Meme Detector, Listing Sniper)
- **Right Panel** (equity sparkline, system stats, by-strategy table)
- **Bottom Bar** (connection/mode + uptime)

All numbers live-drift in dev to simulate activity.

## How to run the example
```bash
cd examples/nautilus-dashboard
npm install
npm run dev
# open http://localhost:3020
```

## Hooking up to your backend
1. Expose a WebSocket endpoint that emits:
   - `system_snapshot` periodically (1s)
   - `pod_update` per strategy as values change
   - `trade` events for the bottom-feed (optional)
2. Replace the mock auto-ticker in `src/state/store.ts` with a real socket subscriber.
3. Map the incoming JSON to Zustand setters (update `system` and `pods`).

## Next steps
- Strategy config modals (per-pod) with full parameter sets
- Backtest panel with run/upload + charts (equity curve, R distribution)
- Risk settings modal with leverage caps, daily loss limits, max concurrent trades
- Prometheus → API proxy for HUD gauges
- Motion polish (Framer Motion micro-interactions from the spec)
