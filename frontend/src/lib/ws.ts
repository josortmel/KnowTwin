import type { KnowtwinWsEvent, KnowtwinWsHandle } from "../types/electron";

export type WsEventType = "new_claim" | "coverage_update" | "topic_change" | "contradiction";

export interface WsEvent {
  type: WsEventType | string;
  data: Record<string, unknown>;
}

export type WsHandler = (event: WsEvent) => void;

// The WebSocket is owned by the main process (window.knowtwin.wsConnect): main
// attaches the ?key from the encrypted store, so the key never reaches the
// renderer (DESIGN.md §4). Returns a { send, close } handle.
export function connectWs(projectId: number, sessionId: string, onEvent: WsHandler): KnowtwinWsHandle {
  const b = window.knowtwin;
  if (!b) return { send: () => {}, close: () => {} };
  return b.wsConnect({ projectId, sessionId }, (ev: KnowtwinWsEvent) => onEvent(ev));
}
