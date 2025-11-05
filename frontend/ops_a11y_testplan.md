# Ops UI Accessibility Test Plan

## Keyboard coverage
- [ ] Load the Command Center and press `Tab` to ensure the skip focus flows: branding → mode switch → pause/resume/flatten/kill controls → main tab list → active tab content.
- [ ] While the mode switch has focus, use `Space` to toggle between PAPER and LIVE and confirm the status badge announces the change.
- [ ] Navigate to every tab trigger with keyboard only, ensuring a visible focus ring remains and `Enter` activates the tab.
- [ ] Open each popover (Date range, Strategies, Symbols) using `Enter`, move through options with arrow keys, and close with `Escape` without trapping focus.

## Screen reader validation (NVDA / VoiceOver)
- [ ] Confirm the status badge announces “Trading enabled/paused” when the state changes (`role="status"` + polite live region).
- [ ] On each venue pill, ensure the reader reports venue name, status, latency, and queue depth without reading decorative animations.
- [ ] Review the global metrics list (`PnL`, `Sharpe`, `Drawdown`, `Positions`) to confirm they are exposed as term/value pairs (`dl > dt/dd`) and updated values are announced politely.
- [ ] Verify that the Kill switch button exposes its additional description warning about disabling trading.

## Automated lint
- [ ] Run `npm install` (or `npm ci`) followed by `npm run lint:a11y` to execute `eslint` with the `jsx-a11y` plugin and ensure zero accessibility lint warnings.

## High-contrast & zoom
- [ ] Activate the browser’s high-contrast / dark mode setting to confirm all color-coded statuses still provide text alternatives.
- [ ] Zoom the interface to 200% and verify that the tab list and Top HUD controls remain reachable without horizontal scrolling.
