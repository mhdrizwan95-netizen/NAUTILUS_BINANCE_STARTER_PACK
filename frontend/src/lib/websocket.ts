import { useEffect, useRef, useCallback } from 'react';
import { useAppStore, useRealTimeActions } from './store';

export interface WebSocketMessage {
  type: string;
  data: any;
  timestamp: number;
}

export interface WebSocketHookResult {
  isConnected: boolean;
  lastMessage: WebSocketMessage | null;
  sendMessage: (message: any) => void;
  reconnect: () => void;
}

class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000; // Start with 1 second
  private maxReconnectDelay = 30000; // Max 30 seconds
  private heartbeatInterval: number | null = null;
  private heartbeatTimeout: number | null = null;
  private url: string;
  private onMessage: (message: WebSocketMessage) => void;
  private onConnect: () => void;
  private onDisconnect: () => void;
  private onError: (error: Event) => void;

  constructor(
    url: string,
    onMessage: (message: WebSocketMessage) => void,
    onConnect: () => void,
    onDisconnect: () => void,
    onError: (error: Event) => void
  ) {
    this.url = url;
    this.onMessage = onMessage;
    this.onConnect = onConnect;
    this.onDisconnect = onDisconnect;
    this.onError = onError;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        this.startHeartbeat();
        this.onConnect();
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          // Clear heartbeat timeout on ack
          if (message.type === 'heartbeat' && this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
          }
          this.onMessage(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        this.stopHeartbeat();
        this.onDisconnect();
        this.handleReconnect(event);
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.onError(error);
      };

    } catch (error) {
      console.error('Failed to create WebSocket connection:', error);
      this.handleReconnect();
    }
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.stopHeartbeat();
  }

  sendMessage(message: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      console.warn('WebSocket is not connected. Message not sent:', message);
    }
  }

  private startHeartbeat(): void {
    // Send heartbeat every 30 seconds
    this.heartbeatInterval = window.setInterval(() => {
      this.sendMessage({ type: 'heartbeat', timestamp: Date.now() });

      // Set timeout for heartbeat response
      this.heartbeatTimeout = window.setTimeout(() => {
        console.warn('Heartbeat timeout - reconnecting...');
        this.disconnect();
        this.connect();
      }, 10000); // 10 second timeout
    }, 30000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  private handleReconnect(event?: CloseEvent): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached', event?.code ?? '');
      return;
    }

    this.reconnectAttempts++;
    const backoff = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );
    const jitter = Math.floor(Math.random() * 500);
    const delay = backoff + jitter;

    console.log(
      `Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`,
      event?.code ?? ''
    );

    window.setTimeout(() => {
      this.connect();
    }, delay);
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Global WebSocket manager instance
let wsManager: WebSocketManager | null = null;
let currentUrl: string | null = null;

const buildWebSocketUrl = (base: string, token: string | undefined): string => {
  try {
    const url = new URL(base, base.startsWith('ws') ? undefined : window.location.origin);
    if (token?.trim()) {
      url.searchParams.set('token', token.trim());
    } else {
      url.searchParams.delete('token');
    }
    return url.toString();
  } catch {
    if (token?.trim()) {
      const delimiter = base.includes('?') ? '&' : '?';
      return `${base}${delimiter}token=${encodeURIComponent(token.trim())}`;
    }
    return base;
  }
};

export function initializeWebSocket(
  onMessage: (message: WebSocketMessage) => void,
  onConnect: () => void,
  onDisconnect: () => void,
  onError: (error: Event) => void,
  token?: string
): WebSocketManager {
  // Use environment variable or default to localhost
  const baseUrl = (import.meta as any).env?.VITE_WS_URL || 'ws://localhost:8002/ws';
  const wsUrl = buildWebSocketUrl(baseUrl, token);

  if (!wsManager || currentUrl !== wsUrl) {
    wsManager?.disconnect();
    wsManager = new WebSocketManager(wsUrl, onMessage, onConnect, onDisconnect, onError);
    currentUrl = wsUrl;
  }

  return wsManager;
}

export function useWebSocket(): WebSocketHookResult {
  const { updateGlobalMetrics, updatePerformances, updateVenues, updateRealTimeData } = useRealTimeActions();
  const opsToken = useAppStore((state) => state.opsAuth.token);
  const lastMessageRef = useRef<WebSocketMessage | null>(null);
  const managerRef = useRef<WebSocketManager | null>(null);
  const actionsRef = useRef({ updateGlobalMetrics, updatePerformances, updateVenues, updateRealTimeData });

  // Update actions ref when they change
  actionsRef.current = { updateGlobalMetrics, updatePerformances, updateVenues, updateRealTimeData };

  const handleMessage = useCallback((message: WebSocketMessage) => {
    lastMessageRef.current = message;

    // Handle different message types using the current actions
    switch (message.type) {
      case 'metrics':
        actionsRef.current.updateGlobalMetrics(message.data);
        break;
      case 'performances':
        actionsRef.current.updatePerformances(message.data);
        break;
      case 'venues':
        actionsRef.current.updateVenues(message.data);
        break;
      case 'heartbeat':
        // Heartbeat response - connection is healthy
        break;
      default:
        console.log('Unhandled WebSocket message:', message);
    }
  }, []); // No dependencies - use actionsRef instead

  const handleConnect = useCallback(() => {
    console.log('WebSocket connected - subscribing to real-time data');
    // Subscribe to real-time updates
    managerRef.current?.sendMessage({
      type: 'subscribe',
      channels: ['metrics', 'performances', 'venues']
    });
  }, []);

  const handleDisconnect = useCallback(() => {
    console.log('WebSocket disconnected');
  }, []);

  const handleError = useCallback((error: Event) => {
    console.error('WebSocket error:', error);
  }, []);

  useEffect(() => {
    const trimmedToken = opsToken.trim();

    if (!trimmedToken) {
      managerRef.current?.disconnect();
      managerRef.current = null;
      currentUrl = null;
      return;
    }

    managerRef.current = initializeWebSocket(
      handleMessage,
      handleConnect,
      handleDisconnect,
      handleError,
      trimmedToken
    );

    if (!managerRef.current.isConnected) {
      managerRef.current.connect();
    }

    return () => {
      // Don't disconnect on unmount - keep connection alive
      // managerRef.current?.disconnect();
    };
  }, [handleConnect, handleDisconnect, handleError, handleMessage, opsToken]);

  const sendMessage = useCallback((message: any) => {
    managerRef.current?.sendMessage(message);
  }, []);

  const reconnect = useCallback(() => {
    managerRef.current?.disconnect();
    managerRef.current?.connect();
  }, []);

  return {
    isConnected: managerRef.current?.isConnected || false,
    lastMessage: lastMessageRef.current,
    sendMessage,
    reconnect,
  };
}

// React Query integration for WebSocket status
export function useWebSocketStatus() {
  return useWebSocket();
}
