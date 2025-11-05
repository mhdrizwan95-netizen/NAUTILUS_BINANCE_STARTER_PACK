import { describe, beforeEach, afterEach, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

describe('initializeWebSocket', () => {
  beforeEach(() => {
    vi.resetModules();
  });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

  it('includes the ops token as a query parameter', async () => {
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
    expect(sockets[0]).toContain('token=ops-token-123');
    expect(sockets[0].startsWith('ws://localhost:8002/ws')).toBe(true);
  });

  it('short circuits when live updates are disabled via env flag', async () => {
    vi.stubEnv('VITE_LIVE_OFF', 'true');
    const { useWebSocket } = await import('./websocket');

    const { result } = renderHook(() => useWebSocket());
    expect(result.current.isConnected).toBe(false);
    expect(result.current.lastMessage).toBeNull();
    result.current.sendMessage({ type: 'noop' }); // should not throw
    result.current.reconnect();
  });
});
