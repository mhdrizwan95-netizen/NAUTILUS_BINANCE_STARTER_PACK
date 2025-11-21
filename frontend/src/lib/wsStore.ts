import type { WebSocketMessage } from "./websocket";

type WSState = {
  connected: boolean;
  lastMessage: WebSocketMessage | null;
};

let state: WSState = {
  connected: false,
  lastMessage: null,
};

const listeners = new Set<() => void>();

const notify = () => {
  listeners.forEach((listener) => {
    try {
      listener();
    } catch (error) {
      console.error("wsStore listener error", error);
    }
  });
};

export const wsSubscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export const wsGetSnapshot = (): WSState => state;

export const wsSetState = (partial: Partial<WSState>) => {
  const nextState: WSState = {
    connected: partial.connected ?? state.connected,
    lastMessage: partial.lastMessage ?? state.lastMessage,
  };

  if (nextState.connected === state.connected && nextState.lastMessage === state.lastMessage) {
    return;
  }

  state = nextState;
  notify();
};
