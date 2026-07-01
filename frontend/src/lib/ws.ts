import { getApiKey } from "./auth";

export type WsEventType = "new_claim" | "coverage_update" | "topic_change" | "contradiction";

export interface WsEvent {
  type: WsEventType;
  data: Record<string, unknown>;
}

export type WsHandler = (event: WsEvent) => void;

export function connectWs(sessionId: string, onEvent: WsHandler): WebSocket {
  const key = getApiKey() ?? "";
  const ws = new WebSocket(`ws://localhost:8090/ws/${sessionId}?key=${encodeURIComponent(key)}`);

  ws.onmessage = (msg) => {
    try {
      const parsed: WsEvent = JSON.parse(msg.data);
      onEvent(parsed);
    } catch {
      // malformed message ignored
    }
  };

  return ws;
}
