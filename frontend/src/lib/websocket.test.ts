import { describe, beforeEach, afterEach, expect, it, vi } from 'vitest';

describe('initializeWebSocket', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
});
