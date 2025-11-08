import { describe, expect, it } from 'vitest';

import { mergeMetricsSnapshot, mergeVenuesSnapshot } from './streamMergers';

describe('streamMergers', () => {
  it('returns existing snapshot when KPIs do not change', () => {
    const existing = {
      kpis: { pnl: 10, sharpe: 1.2 },
      equityByStrategy: [{ id: 'alpha' }],
    };
    const unchanged = mergeMetricsSnapshot(existing, { pnl: 10, sharpe: 1.2 });
    expect(unchanged).toBe(existing);

    const changed = mergeMetricsSnapshot(existing, { pnl: 20 });
    expect(changed).not.toBe(existing);
    expect(changed.kpis.pnl).toBe(20);
  });

  it('only updates venues when array content changes', () => {
    const venues = [
      { name: 'binance', status: 'ok' },
      { name: 'bybit', status: 'down' },
    ];
    const existing = { venues };
    const unchanged = mergeVenuesSnapshot(existing, [...venues]);
    expect(unchanged).toBe(existing);

    const updated = mergeVenuesSnapshot(existing, [
      { name: 'binance', status: 'warn' },
      { name: 'bybit', status: 'down' },
    ]);
    expect(updated).not.toBe(existing);
    expect(updated).toMatchObject({
      venues: [
        { name: 'binance', status: 'warn' },
        { name: 'bybit', status: 'down' },
      ],
    });
  });
});
