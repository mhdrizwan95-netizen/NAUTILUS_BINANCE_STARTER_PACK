import { useEffect, useRef, useCallback, useState, useMemo, useSyncExternalStore } from "react";
import { useShallow } from "zustand/react/shallow";

import { issueWebsocketSession } from "./api";
import { useTradingStore, type PriceTick } from "./tradingStore";

// ... (imports)

export function useWebSocket(): WebSocketHookResult {
  // ... (existing checks)

  // Use environment variable or default to localhost:8003 (Engine)
  const baseUrl = import.meta.env?.VITE_WS_URL ?? "ws://localhost:8003/ws";
  const url = new URL(baseUrl);
  url.searchParams.set("token", session);
  const wsUrl = url.toString();
  const updateStrategy = useTradingStore((state) => state.updateStrategy);
  const updateVenue = useTradingStore((state) => state.updateVenue);
  const setSystemHealth = useTradingStore((state) => state.setSystemHealth);

  const managerRef = useRef<WebSocketManager | null>(null);

  // Batching Refs
  const priceBufferRef = useRef<PriceTick[]>([]);
  const batchTimeoutRef = useRef<number | null>(null);

  const flushBatch = useCallback(() => {
    if (priceBufferRef.current.length > 0) {
      updatePrices(priceBufferRef.current);
      priceBufferRef.current = [];
    }
    batchTimeoutRef.current = null;
  }, [updatePrices]);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    wsSetState({ lastMessage: message });

    switch (message.type) {
      case "market.tick":
        // High-frequency data: Batch it
        if (message.data && typeof message.data === 'object') {
          const tick = message.data as any;
          priceBufferRef.current.push({
            symbol: tick.symbol,
            price: tick.price,
            volume: tick.volume || 0,
            timestamp: tick.ts * 1000
          });

          if (!batchTimeoutRef.current) {
            batchTimeoutRef.current = window.setTimeout(flushBatch, 50); // 50ms throttle (20fps)
          }
        }
        break;

      case "account_update":
        // Medium-frequency: Direct update
        if (message.data) {
          setPortfolio(message.data as any);
        }
        break;

      case "strategy.performance":
        if (Array.isArray(message.data)) {
          message.data.forEach((strat: any) => {
            updateStrategy(strat.name, strat);
          });
        }
        break;

      case "venue.status":
        if (message.data) {
          const venue = message.data as any;
          updateVenue(venue.name, venue);
        }
        break;

      case "heartbeat":
        break;

      default:
        // wsDevLog("Unhandled WebSocket message:", message);
        break;
    }
  }, [flushBatch, setPortfolio, updateStrategy, updateVenue]);

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
