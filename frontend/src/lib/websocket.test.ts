import { describe, beforeEach, afterEach, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

describe('websocket utilities', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.clearAllMocks();
    try {
      vi.doUnmock('./store');
    } catch (error) {
      if (error instanceof Error && !/is not mocked/i.test(error.message)) {
        throw error;
      }
    }
    try {
      vi.doUnmock('./api');
    } catch (error) {
      if (error instanceof Error && !/is not mocked/i.test(error.message)) {
        throw error;
      }
    }
  });

  it('includes the session token as a query parameter', async () => {
    const sockets: string[] = [];

    class MockWebSocket {
      static OPEN = 1;
      url: string;
      readyState = MockWebSocket.OPEN;
      onopen: ((ev: Event) => unknown) | null = null;
      onmessage: ((ev: MessageEvent) => unknown) | null = null;
      onclose: ((ev: CloseEvent) => unknown) | null = null;
      onerror: ((ev: Event) => unknown) | null = null;

      constructor(url: string) {
        this.url = url;
        sockets.push(url);
      }

      close(): void {
        /** noop */
      }

      send(): void {
        /** noop */
      }
    }

    vi.stubEnv('VITE_WS_URL', 'ws://localhost:8002/ws');
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);

    const { initializeWebSocket } = await import('./websocket');
    const manager = initializeWebSocket(
      () => {},
      () => {},
      () => {},
      () => {},
      'ops-token-123'
    );

    manager.connect();

    expect(sockets).toHaveLength(1);
    expect(sockets[0]).toContain('session=ops-token-123');
    expect(sockets[0].startsWith('ws://localhost:8002/ws')).toBe(true);
  });

  it('returns disabled controls when live updates are disabled via env flag', async () => {
    const useAppStoreMock = vi.fn(() => ({ token: '', actor: '' }));
    const useRealTimeActionsMock = vi.fn(() => ({
      updateGlobalMetrics: vi.fn(),
      updatePerformances: vi.fn(),
      updateVenues: vi.fn(),
      updateRealTimeData: vi.fn(),
    }));
    const issueSessionMock = vi.fn();

    vi.doMock('./store', () => ({
      useAppStore: useAppStoreMock,
      useRealTimeActions: useRealTimeActionsMock,
    }));

    vi.doMock('./api', () => ({
      issueWebsocketSession: issueSessionMock,
    }));

    const { useWebSocket, __setLiveDisabledOverride } = await import('./websocket');

    __setLiveDisabledOverride(true);

    const { result } = renderHook(() => useWebSocket());
    expect(result.current.isConnected).toBe(false);
    expect(result.current.lastMessage).toBeNull();
    expect(typeof result.current.sendMessage).toBe('function');
    expect(typeof result.current.reconnect).toBe('function');

    // Defensive: the noop handlers should not throw even if invoked
    expect(() => result.current.sendMessage({ type: 'noop' })).not.toThrow();
    expect(() => result.current.reconnect()).not.toThrow();

    expect(useAppStoreMock).not.toHaveBeenCalled();
    expect(useRealTimeActionsMock).not.toHaveBeenCalled();
    expect(issueSessionMock).not.toHaveBeenCalled();
    __setLiveDisabledOverride(null);
  });
});
