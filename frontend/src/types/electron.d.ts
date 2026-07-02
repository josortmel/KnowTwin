// The window.knowtwin bridge contract (DESIGN.md §4). The renderer programs
// against this; the MAIN process owns the API key and attaches it — the key
// never crosses into the renderer. There is deliberately NO getToken/getApiKey.

export interface KnowtwinFetchResult<T = unknown> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: "no_api_key" | "network" | "invalid_path" | "redirect";
  /** Seconds from the Retry-After header on a 429, when present. */
  retryAfter?: number;
}

export interface KnowtwinFetchOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

/** Real-time interview event, forwarded from the main-owned WebSocket. */
export interface KnowtwinWsEvent {
  type: string;
  data: Record<string, unknown>;
}

/** Handle for a main-owned WebSocket. `close()` unsubscribes + closes. */
export interface KnowtwinWsHandle {
  send(data: string): void;
  close(): void;
}

export interface KnowtwinUploadResult {
  ok: boolean;
  status?: number;
  data?: unknown;
  filename?: string;
  error?: string;
  canceled?: boolean;
}

export interface KnowtwinBridge {
  /** Main attaches `Authorization: Bearer <key>`. Renderer never sees the key. */
  fetch<T = unknown>(path: string, opts?: KnowtwinFetchOptions): Promise<KnowtwinFetchResult<T>>;
  /** Auth screen only. Trims + rejects empty. Stored encrypted in main. */
  setApiKey(key: string): Promise<boolean>;
  /** Pure boolean — never the key nor a hash of it. */
  hasApiKey(): boolean;
  /** For 401 / manual rotation. */
  clearApiKey(): Promise<void>;
  saveFile(content: string, filename: string): Promise<{ ok: boolean; path?: string; canceled?: boolean }>;
  /** Renderer sends the File's bytes; main validates + POSTs multipart to
   *  /projects/{project_id}/documents/upload. The Bearer key stays in main. */
  uploadDocument(args: {
    project_id?: number;
    visibility?: "public" | "private";
    trust_hint?: string;
    filename: string;
    bytes: ArrayBuffer;
  }): Promise<KnowtwinUploadResult>;
  /** Interview voice note (recorded in-app) — bytes → POST /interviews/{session_id}/voice. */
  uploadVoice(args: { session_id: string; filename: string; bytes: ArrayBuffer }): Promise<KnowtwinUploadResult>;
  /** App config — the configurable API base URL. */
  getConfig(): Promise<{ apiBaseUrl: string }>;
  setConfig(cfg: { apiBaseUrl: string }): Promise<{ ok: boolean; error?: string }>;
  /** Opens a main-owned WebSocket to the interview stream. The key is attached
   *  in main and never reaches the renderer. Returns a send/close handle. */
  wsConnect(args: { projectId: number; sessionId: string }, onEvent: (event: KnowtwinWsEvent) => void): KnowtwinWsHandle;
}

declare global {
  interface Window {
    knowtwin: KnowtwinBridge;
  }
}
