# Nautilus Dashboard Example (Standalone)

This is a **standalone Next.js + Tailwind + Zustand** prototype of the **Nautilus Trading Command Center**.
It implements the HUD, Strategy Matrix pods, Right Panel performance, and Bottom Bar with mock live updates.

## Quick start

```bash
# inside examples/nautilus-dashboard
npm install
npm run dev
# open http://localhost:3020
```

> This example app is self-contained and does **not** connect to your trading backend yet.
Hook it up to your FastAPI/WebSocket telemetry when ready (see `docs/telemetry-contracts.md` in the root deck).
