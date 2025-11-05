import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { usePolling } from './hooks';

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('skips updates when comparator deems payload unchanged', async () => {
    const responses = [
      { status: 'running', progress: 0 },
      { status: 'running', progress: 0 },
      { status: 'done', progress: 1 },
    ];
    const poller = vi
      .fn()
      .mockImplementation(() => Promise.resolve(responses.shift() ?? responses[responses.length - 1]));

    const comparator = vi.fn((prev, next) => {
      if (!prev || !next) return Object.is(prev, next);
      return JSON.stringify(prev) === JSON.stringify(next);
    });

    const { result } = renderHook(() => usePolling(poller, 100, true, comparator));

    await act(async () => {
      vi.advanceTimersByTime(0);
      await Promise.resolve();
    });

    const firstRef = result.current.data;
    expect(firstRef).toMatchObject({ status: 'running', progress: 0 });

    await act(async () => {
      vi.advanceTimersByTime(100);
      await Promise.resolve();
    });

    // Second payload equals the first – no state update.
    expect(result.current.data).toBe(firstRef);

    await act(async () => {
      vi.advanceTimersByTime(100);
      await Promise.resolve();
    });

    expect(result.current.data).toMatchObject({ status: 'done', progress: 1 });
    expect(result.current.data).not.toBe(firstRef);
    expect(comparator).toHaveBeenCalled();
  });

  it('disables polling when VITE_LIVE_OFF flag is true', async () => {
    vi.stubEnv('VITE_LIVE_OFF', 'true');
    const poller = vi.fn();
    renderHook(() => usePolling(poller, 100));

    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });

    expect(poller).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });
});
