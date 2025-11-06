import '@testing-library/jest-dom';
import { beforeAll, afterEach, afterAll } from 'vitest';

class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}

const createStorage = () => new MemoryStorage();

const ensureStorage = (prop: 'localStorage' | 'sessionStorage') => {
  const existing = (globalThis as Record<string, unknown>)[prop];
  if (!existing || typeof (existing as Storage).getItem !== 'function') {
    Object.defineProperty(globalThis, prop, {
      value: createStorage(),
      configurable: true,
      writable: true,
    });
  }
  if (typeof window !== 'undefined') {
    const win = window as unknown as Record<string, unknown>;
    if (!win[prop] || typeof (win[prop] as Storage).getItem !== 'function') {
      Object.defineProperty(window, prop, {
        value: (globalThis as Record<string, unknown>)[prop],
        configurable: true,
        writable: true,
      });
    }
  }
};

ensureStorage('localStorage');
ensureStorage('sessionStorage');

// Mock WebSocket
global.WebSocket = class MockWebSocket {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readyState = 1; // OPEN

  constructor() {
    // Simulate connection
    setTimeout(() => {
      this.onopen?.(new Event('open'));
    }, 0);
  }

  send() {}
  close() {
    this.readyState = 3; // CLOSED
    this.onclose?.(new CloseEvent('close'));
  }
} as any;

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});

// Setup MSW server
const mswDisabled = process.env.MSW_DISABLED === 'true';

export const server = await (async () => {
  if (mswDisabled) {
    return null;
  }
  const [{ setupServer }, { handlers }] = await Promise.all([
    import('msw/node'),
    import('./mocks/handlers'),
  ]);
  const instance = setupServer(...handlers);

  beforeAll(() => instance.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => instance.resetHandlers());
  afterAll(() => instance.close());

  return instance;
})();
