import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Set up API mocking for E2E tests
    await page.route('**/api/**', async (route) => {
      const url = route.request().url();

      if (url.includes('/api/strategies')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
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
          ]),
        });
      } else if (url.includes('/api/metrics/summary')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
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
          }),
        });
      } else if (url.includes('/api/positions')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              symbol: 'BTC/USDT',
              qty: 0.5,
              entry: 45000,
              mark: 46500,
              pnl: 750,
            },
          ]),
        });
      } else if (url.includes('/api/trades/recent')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
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
          ]),
        });
      } else if (url.includes('/api/alerts')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              id: 'alert-1',
              timestamp: Date.now() - 120000,
              type: 'warning',
              message: 'High volatility detected on BTC/USDT',
              strategyId: 'hmm',
            },
          ]),
        });
      } else if (url.includes('/api/health')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            venues: [
              {
                name: 'Binance',
                status: 'ok',
                latencyMs: 45,
                queue: 2,
              },
            ],
          }),
        });
      } else {
        await route.continue();
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
    await expect(page.getByText('BTC/USDT')).toBeVisible();

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
    await page.getByRole('button', { name: /switch/i }).click();

    // Should now show live mode styling (the switch should be checked)
    const switchElement = page.locator('[data-testid="mode-switch"]');
    await expect(switchElement).toHaveAttribute('data-checked', 'true');
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
