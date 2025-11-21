# Nautilus Trading Command Center

This is a code bundle for Nautilus Trading Command Center. The original project is available at https://www.figma.com/design/lFKMXdhG7MLDvMytUsmzEq/Nautilus-Trading-Command-Center.

## Running the code

Run `npm i` to install the dependencies.

Run `npm run dev` to start the development server.

## End-to-end tests / Playwright

-   Playwright now targets the running Command Center served by `hmm_ops` (`http://localhost:8002`). Make sure `make dry-run` or `docker compose up ops` is active before running `npx playwright test`.
-   Override the URL with `PW_BASE_URL=http://your-host:port npx playwright test` if your stack is reachable elsewhere.
-   If you still want Playwright to spin up a dev server automatically (e.g., for quick UI-only checks), provide `PW_WEB_SERVER_CMD="npm run dev -- --host 127.0.0.1 --port 4176"` so the config knows how to start/stop it.

## Debugging render loops

-   Dev builds ship with `useWhyDidYouUpdate` + render counters (see `src/lib/debug/why.ts`). Open the browser console to inspect `why-did-you-update` or `render-count` logs for hot components such as `App`, `TopHUD`, and `BacktestingTab`.
-   To disable live WebSocket traffic and polling while investigating tests, export `VITE_LIVE_OFF=true` (or set it in `.env.test`). The command center will stub real-time channels but continue rendering static data.
-   Run `npm run test` to execute the Vitest suites, including loop regression tests:
    -   `src/components/forms/DynamicParamForm.test.tsx`
    -   `src/lib/hooks.test.tsx`
    -   `src/lib/streamMergers.test.ts`
    -   `src/lib/websocket.test.tsx`

## Reviewer checklist (render-loop regression guard)

1. Are new effects gated by dependency equality (or memoized callbacks) to avoid mutating their own dependencies?
2. Do polling hooks or timers skip updates when payloads are unchanged?
3. Are WebSocket or subscription handlers merging into cache/state without returning new references needlessly?
4. Does the component stabilize within <=5 renders (check console render counters in dev)?
5. Are live-update features disabled in tests via `VITE_LIVE_OFF` when necessary?
