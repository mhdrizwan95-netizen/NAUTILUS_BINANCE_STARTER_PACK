import { useEffect, useRef, useCallback, useState, useMemo, useSyncExternalStore } from "react";
import { useShallow } from "zustand/react/shallow";

import { issueWebsocketSession } from "./api";
import { useAppStore, useRealTimeActions } from "./store";
import { wsGetSnapshot, wsSetState, wsSubscribe } from "./wsStore";
import type { GlobalMetrics, StrategyPerformance, Venue } from "../types/trading";

type OutgoingMessage = Record<string, unknown>;

const wsDevLog = (...args: unknown[]) => {
  if (import.meta.env.DEV) {
    console.warn(...args);
  }
};

export interface WebSocketMessage<T = unknown> {
  type: string;
  data: T;
  timestamp: number;
}

export interface WebSocketHookResult {
  isConnected: boolean;
  lastMessage: WebSocketMessage | null;
  sendMessage: (message: OutgoingMessage) => void;
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
    onError: (error: Event) => void,
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
        wsDevLog("WebSocket connected");
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        this.startHeartbeat();
        this.onConnect();
      };

      this.ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as Partial<WebSocketMessage>;
          if (!parsed || typeof parsed.type !== "string") {
            throw new Error("Malformed message");
          }
          const message: WebSocketMessage = {
            type: parsed.type,
            data: parsed.data ?? null,
            timestamp: parsed.timestamp ?? Date.now(),
          };
          // Clear heartbeat timeout on ack
          if (message.type === "heartbeat" && this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
          }
          this.onMessage(message);
        } catch (error) {
          console.error("Failed to parse WebSocket message:", error);
        }
      };

      this.ws.onclose = (event) => {
        wsDevLog("WebSocket disconnected:", event.code, event.reason);
        this.stopHeartbeat();
        this.onDisconnect();
        this.handleReconnect(event);
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        this.onError(error);
      };
    } catch (error) {
      console.error("Failed to create WebSocket connection:", error);
      this.handleReconnect();
    }
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }
    this.stopHeartbeat();
  }

  sendMessage(message: OutgoingMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      console.warn("WebSocket is not connected. Message not sent:", message);
    }
  }

  private startHeartbeat(): void {
    // Send heartbeat every 30 seconds
    this.heartbeatInterval = window.setInterval(() => {
      this.sendMessage({ type: "heartbeat", timestamp: Date.now() });

      // Set timeout for heartbeat response
      this.heartbeatTimeout = window.setTimeout(() => {
        console.warn("Heartbeat timeout - reconnecting...");
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
      console.error("Max reconnection attempts reached", event?.code ?? "");
      return;
    }

    this.reconnectAttempts++;
    const backoff = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.maxReconnectDelay,
    );
    const jitter = Math.floor(Math.random() * 500);
    const delay = backoff + jitter;

    wsDevLog(
      `Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`,
      event?.code ?? "",
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
let liveDisabledOverride: boolean | null = null;

const isGlobalMetricsPayload = (data: unknown): data is GlobalMetrics =>
  typeof data === "object" && data !== null;

const isStrategyPerformanceArray = (data: unknown): data is StrategyPerformance[] =>
  Array.isArray(data);

const isVenueArray = (data: unknown): data is Venue[] => Array.isArray(data);

const buildWebSocketUrl = (base: string, session: string): string => {
  try {
    const url = new URL(base, base.startsWith("ws") ? undefined : window.location.origin);
    url.searchParams.set("session", session);
    return url.toString();
  } catch {
    const delimiter = base.includes("?") ? "&" : "?";
    return `${base}${delimiter}session=${encodeURIComponent(session)}`;
  }
};

export const __setLiveDisabledOverride = (value: boolean | null) => {
  liveDisabledOverride = value;
};

const resolveLiveDisabled = (): boolean => {
  if (liveDisabledOverride !== null) {
    return liveDisabledOverride;
  }
  return (import.meta.env?.VITE_LIVE_OFF ?? "false") === "true";
};

export function initializeWebSocket(
  onMessage: (message: WebSocketMessage) => void,
  onConnect: () => void,
  onDisconnect: () => void,
  onError: (error: Event) => void,
  session: string,
): WebSocketManager {
  // Use environment variable or default to localhost
  const baseUrl = import.meta.env?.VITE_WS_URL ?? "ws://localhost:8002/ws";
  const wsUrl = buildWebSocketUrl(baseUrl, session);

  if (!wsManager || currentUrl !== wsUrl) {
    wsManager?.disconnect();
    wsManager = new WebSocketManager(wsUrl, onMessage, onConnect, onDisconnect, onError);
    currentUrl = wsUrl;
  }

  return wsManager;
}

export function useWebSocket(): WebSocketHookResult {
  const isTestMode =
    (typeof import.meta !== "undefined" && import.meta.env?.MODE === "test") ||
    (typeof import.meta !== "undefined" && import.meta.env?.VITE_DISABLE_WS === "1") ||
    (typeof globalThis !== "undefined" &&
      Boolean((globalThis as { __NAUTILUS_DISABLE_WS__?: boolean }).__NAUTILUS_DISABLE_WS__));

  const liveDisabled = resolveLiveDisabled();
  const disabledResult: WebSocketHookResult = useMemo(() => {
    const noop = () => {};
    return {
      isConnected: false,
      lastMessage: null,
      sendMessage: noop,
      reconnect: noop,
    } satisfies WebSocketHookResult;
  }, []);

  if (liveDisabled || isTestMode) {
    return disabledResult;
  }

  const { updateGlobalMetrics, updatePerformances, updateVenues, updateRealTimeData } =
    useRealTimeActions();
  const [opsToken, opsActor] = useAppStore(
    useShallow((state) => [state.opsAuth.token, state.opsAuth.actor] as const),
  );
  const managerRef = useRef<WebSocketManager | null>(null);
  const actionsRef = useRef({
    updateGlobalMetrics,
    updatePerformances,
    updateVenues,
    updateRealTimeData,
  });
  const [wsSession, setWsSession] = useState<string | null>(null);
  const lastCredentialsRef = useRef<string | null>(null);
  const sessionRequestInFlight = useRef(false);
  const lastSessionFailureRef = useRef<number>(0);

  // Update actions ref when they change
  actionsRef.current = {
    updateGlobalMetrics,
    updatePerformances,
    updateVenues,
    updateRealTimeData,
  };

  const handleMessage = useCallback((message: WebSocketMessage) => {
    wsSetState({ lastMessage: message });

    // Handle different message types using the current actions
    switch (message.type) {
      case "metrics":
        if (isGlobalMetricsPayload(message.data)) {
          actionsRef.current.updateGlobalMetrics(message.data);
        }
        break;
      case "performances":
        if (isStrategyPerformanceArray(message.data)) {
          actionsRef.current.updatePerformances(message.data);
        }
        break;
      case "venues":
        if (isVenueArray(message.data)) {
          actionsRef.current.updateVenues(message.data);
        }
        break;
      case "heartbeat":
        // Heartbeat response - connection is healthy
        break;
      default:
        wsDevLog("Unhandled WebSocket message:", message);
    }
  }, []); // No dependencies - use actionsRef instead

  const handleConnect = useCallback(() => {
    wsDevLog("WebSocket connected - subscribing to real-time data");
    wsSetState({ connected: true });
    // Subscribe to real-time updates
    managerRef.current?.sendMessage({
      type: "subscribe",
      channels: ["metrics", "performances", "venues"],
    });
  }, []);

  const handleDisconnect = useCallback(() => {
    wsDevLog("WebSocket disconnected");
    wsSetState({ connected: false });
  }, []);

  const handleError = useCallback((error: Event) => {
    console.error("WebSocket error:", error);
  }, []);

  useEffect(() => {
    const trimmedToken = opsToken.trim();
    const trimmedActor = opsActor.trim();
    if (!trimmedToken || !trimmedActor) {
      setWsSession((prev) => (prev === null ? prev : null));
      managerRef.current?.disconnect();
      managerRef.current = null;
      currentUrl = null;
      lastCredentialsRef.current = null;
      return;
    }

    const credentialSignature = `${trimmedToken}:${trimmedActor}`;
    if (wsSession && lastCredentialsRef.current === credentialSignature) {
      return;
    }

    if (sessionRequestInFlight.current) {
      return;
    }

    const now = Date.now();
    if (
      lastCredentialsRef.current === credentialSignature &&
      !wsSession &&
      now - lastSessionFailureRef.current < 5000
    ) {
      return;
    }

    let cancelled = false;
    const requestSession = async () => {
      sessionRequestInFlight.current = true;
      try {
        const response = await issueWebsocketSession({
          token: trimmedToken,
          actor: trimmedActor,
        });
        if (cancelled) {
          return;
        }
        setWsSession((prev) => (prev === response.session ? prev : response.session));
        lastSessionFailureRef.current = 0;
      } catch (error) {
        console.error("Failed to issue WebSocket session:", error);
        if (!cancelled) {
          setWsSession((prev) => (prev === null ? prev : null));
          lastSessionFailureRef.current = Date.now();
        }
      } finally {
        lastCredentialsRef.current = credentialSignature;
        sessionRequestInFlight.current = false;
      }
    };

    void requestSession();

    return () => {
      cancelled = true;
      sessionRequestInFlight.current = false;
    };
  }, [opsToken, opsActor, wsSession]);

  useEffect(() => {
    const trimmedToken = opsToken.trim();

    if (!trimmedToken) {
      managerRef.current?.disconnect();
      managerRef.current = null;
      currentUrl = null;
      return;
    }

    if (!wsSession) {
      return;
    }

    managerRef.current = initializeWebSocket(
      handleMessage,
      handleConnect,
      handleDisconnect,
      handleError,
      wsSession,
    );

    if (!managerRef.current.isConnected) {
      managerRef.current.connect();
    }

    return () => {
      // Don't disconnect on unmount - keep connection alive
      // managerRef.current?.disconnect();
    };
  }, [handleConnect, handleDisconnect, handleError, handleMessage, opsToken, wsSession]);

  const sendMessage = useCallback((message: OutgoingMessage) => {
    managerRef.current?.sendMessage(message);
  }, []);

  const reconnect = useCallback(() => {
    managerRef.current?.disconnect();
    managerRef.current?.connect();
  }, []);

  const snapshot = useSyncExternalStore(wsSubscribe, wsGetSnapshot, wsGetSnapshot);

  return useMemo(
    () => ({
      isConnected: snapshot.connected,
      lastMessage: snapshot.lastMessage,
      sendMessage,
      reconnect,
    }),
    [snapshot, sendMessage, reconnect],
  );
}

// React Query integration for WebSocket status
export function useWebSocketStatus() {
  return useWebSocket();
}
