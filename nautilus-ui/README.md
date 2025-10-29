# Nautilus Trading Command Center

Revamped neural-dark trading cockpit inspired by the Nautilus Figma reference. The UI runs entirely in Next.js 14 with simulated data streams for quick iteration.

## Quick start

```bash
cd nautilus-ui
npm install
npm run dev    # http://localhost:5173
```

## Highlights

- Framer Motion boot sequence + glassmorphism HUD
- Strategy × venue matrix with animated pods and sparklines
- Detail panel with equity curve, confidence timeline, and trade log
- Dual-feed bottom bar (alerts + recent executions)
- Lightweight configuration modal for global + per-strategy knobs
- Tailwind neural-dark tokens and Lucide iconography

Data is generated client-side via `lib/mockData.ts`. Update that module (or replace the interval in `app/page.tsx`) to wire in live WebSocket metrics from your engine.

## File tour

- `app/page.tsx` – entry point + state orchestration
- `components/TopHUD.tsx` – mode toggle, global metrics, venue health
- `components/StrategyMatrix.tsx` / `StrategyPod.tsx` – grid of strategy performance cards
- `components/RightPanel.tsx` – deep-dive drawer (charts built with Recharts)
- `components/BottomBar.tsx` – alerts & recent trades feeds
- `components/SettingsModal.tsx` – configurable risk/strategy presets
- `lib/mockData.ts` – mock streams / colour helpers
- `lib/types.ts` – shared domain + settings types

## Customisation hints

- Update colours / fonts in `tailwind.config.ts` and `styles/globals.css`
- Extend the modal sections for new strategies or risk rails
- Swap the generated mock data with WebSocket updates, REST polling, or Zustand/React Query stores as needed
- Recharts is used sparingly (mini sparkline + equity line). Replace with your preferred charting library if required

Happy hacking ⚡
