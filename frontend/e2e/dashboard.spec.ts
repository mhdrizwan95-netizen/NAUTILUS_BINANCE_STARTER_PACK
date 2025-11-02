import { test, expect, type Route } from '@playwright/test';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Set up API mocking for E2E tests
    const fulfillJson = async (route: Route, body: unknown, status = 200) => {
      await route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    };

    await page.addInitScript(() => {
      (window as any).__NAUTILUS_DISABLE_PERSIST__ = true;
    });

    page.on('console', (msg) => console.log('[console]', msg.type(), msg.text()));

    await page.route('**/aggregate/**', async (route) => {
      const url = route.request().url();
      if (url.endsWith('/aggregate/portfolio')) {
        await fulfillJson(route, {
          equity_usd: 425000,
          cash_usd: 175000,
          gain_usd: 12500,
          return_pct: 0.032,
          baseline_equity_usd: 412500,
          last_refresh_epoch: Math.floor(Date.now() / 1000),
        });
        return;
      }
      if (url.endsWith('/aggregate/exposure')) {
        await fulfillJson(route, {
          totals: { exposure_usd: 250000, count: 5, venues: 2 },
          by_symbol: {
            'BTCUSDT.BINANCE': {
              qty_base: 1.25,
              last_price_usd: 59000,
              exposure_usd: 73750,
            },
            'ETHUSDT.BINANCE': {
              qty_base: 10,
              last_price_usd: 3200,
              exposure_usd: 32000,
            },
          },
        });
        return;
      }
      if (url.endsWith('/aggregate/pnl')) {
        await fulfillJson(route, {
          realized: { BINANCE: 6800, IBKR: 2200 },
          unrealized: { BINANCE: 5400, IBKR: -800 },
        });
        return;
      }
      await route.continue();
    });

    await page.route('**/api/**', async (route) => {
      const url = route.request().url();

      if (url.includes('/api/strategies')) {
        await fulfillJson(route, [
            {
              id: 'hmm',
              name: 'HMM',
              kind: 'HMM',
              status: 'running',
              symbols: ['BTC/USDT', 'ETH/USDT'],
              paramsSchema: { fields: [] },
              performance: {
                pnl: 1250.50,
                equitySeries: [
                  { t: '2025-01-01', equity: 10000 },
                  { t: '2025-01-02', equity: 11250 },
                ],
                winRate: 0.68,
                sharpe: 1.8,
                drawdown: 0.05,
              },
            },
          ]);
      } else if (url.includes('/api/metrics/summary')) {
        await fulfillJson(route, {
            kpis: {
              totalPnl: 1847.25,
              winRate: 0.62,
              sharpe: 1.45,
              maxDrawdown: 0.08,
              openPositions: 12,
            },
            equityByStrategy: [
              { t: '2025-01-01', HMM: 10000 },
              { t: '2025-01-02', HMM: 11847 },
            ],
            pnlBySymbol: [
              { symbol: 'BTC/USDT', pnl: 1250.50 },
              { symbol: 'ETH/USDT', pnl: 596.75 },
            ],
            returns: [0.02, -0.03, 0.015, 0.008, -0.005],
          });
      } else if (url.includes('/api/positions')) {
        await fulfillJson(route, [
            {
              symbol: 'BTC/USDT',
              qty: 0.5,
              entry: 45000,
              mark: 46500,
              pnl: 750,
            },
          ]);
      } else if (url.includes('/api/trades/recent')) {
        await fulfillJson(route, [
            {
              id: 'trade-1',
              timestamp: Date.now() - 300000,
              symbol: 'BTC/USDT',
              side: 'buy',
              quantity: 0.5,
              price: 45000,
              pnl: 750,
              strategyId: 'hmm',
              venueId: 'binance',
            },
          ]);
      } else if (url.includes('/api/alerts')) {
        await fulfillJson(route, [
            {
              id: 'alert-1',
              timestamp: Date.now() - 120000,
              type: 'warning',
              message: 'High volatility detected on BTC/USDT',
              strategyId: 'hmm',
            },
          ]);
      } else if (url.includes('/api/health')) {
        await fulfillJson(route, {
            venues: [
              {
                name: 'Binance',
                status: 'ok',
                latencyMs: 45,
                queue: 2,
              },
            ],
          });
      } else {
        await fulfillJson(route, {});
      }
    });

    await page.goto('/');
  });

  test('should load the dashboard with all components', async ({ page }) => {
    // Check if the main branding is visible
    await expect(page.getByText('NAUTILUS')).toBeVisible();
    await expect(page.getByText('TERMINAL')).toBeVisible();

    // Check if mode toggle is present
    await expect(page.getByText('PAPER')).toBeVisible();
    await expect(page.getByText('LIVE')).toBeVisible();

    // Check if dashboard tab is active by default
    await expect(page.getByRole('tab', { name: 'Dashboard' })).toHaveAttribute('data-state', 'active');

    // Wait for dashboard data to load
    await page.waitForTimeout(1000);

    // Check if KPI metrics are displayed
    await expect(page.getByText('$1,847.25')).toBeVisible();
    await expect(page.getByText('62%')).toBeVisible();
    await expect(page.getByText('1.45')).toBeVisible();

    // Check if positions table is present
    await expect(page.getByText('Open Positions')).toBeVisible();
    const positionsTable = page.getByRole('table', { name: /open positions/i });
    await expect(positionsTable.getByRole('cell', { name: 'BTC/USDT' })).toBeVisible();

    // Check if recent trades are displayed
    await expect(page.getByText('Recent Trades')).toBeVisible();

    // Check if alerts are shown
    await expect(page.getByText('Alerts')).toBeVisible();
  });

  test('should switch between tabs', async ({ page }) => {
    // Click on Strategy tab
    await page.getByRole('tab', { name: 'Strategy' }).click();
    await expect(page.getByRole('tab', { name: 'Strategy' })).toHaveAttribute('data-state', 'active');

    // Click on Backtesting tab
    await page.getByRole('tab', { name: 'Backtesting / ML' }).click();
    await expect(page.getByRole('tab', { name: 'Backtesting / ML' })).toHaveAttribute('data-state', 'active');

    // Go back to Dashboard
    await page.getByRole('tab', { name: 'Dashboard' }).click();
    await expect(page.getByRole('tab', { name: 'Dashboard' })).toHaveAttribute('data-state', 'active');
  });

  test('should toggle between paper and live mode', async ({ page }) => {
    // Initially should be in paper mode
    await expect(page.getByText('PAPER')).toBeVisible();

    // Click the mode switch
    const modeSwitch = page.getByRole('switch', { name: /trading mode/i });
    await modeSwitch.click();

    // Should now show live mode styling (the switch should be checked)
    await expect(modeSwitch).toHaveAttribute('aria-checked', 'true');
  });

  test('should show loading states initially', async ({ page }) => {
    // Reload page to see loading states
    await page.reload();

    // Check for skeleton loaders (if implemented)
    // This would depend on the actual loading implementation
    await page.waitForTimeout(500);
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Mock a failed API response
    await page.route('**/api/metrics/summary', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.reload();

    // Should still show the UI (error boundaries should catch this)
    await expect(page.getByText('NAUTILUS')).toBeVisible();

    // Check if error toast appears (if implemented)
    // await expect(page.getByText(/failed to refresh/i)).toBeVisible();
  });

  test('should be responsive on different screen sizes', async ({ page }) => {
    // Test mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });

    // Check if critical elements are still visible
    await expect(page.getByText('NAUTILUS')).toBeVisible();

    // Check if tabs are accessible (might be in a dropdown or scrollable)
    await expect(page.getByRole('tab', { name: 'Dashboard' })).toBeVisible();

    // Test tablet viewport
    await page.setViewportSize({ width: 768, height: 1024 });
    await expect(page.getByText('NAUTILUS')).toBeVisible();
  });
});
