import { app, BrowserWindow, ipcMain, dialog, session } from "electron";
import path from "node:path";
import { writeFile } from "node:fs/promises";
import { WebSocket as WsClient } from "ws";
import { hasApiKey, setApiKey, clearApiKey, decryptApiKey } from "./secure-store";
import { getApiBase, setApiBase } from "./config-store";
import { resolveApiUrl } from "./lib/api-url";

// Pin the app name BEFORE any electron-store is instantiated (the stores are
// lazy for this reason). Otherwise app.getName() can resolve to "Electron" on
// some dev launches and a different name on others → two different userData
// dirs → the persisted API key saved under one isn't found under the other, so
// the app keeps asking for the key on every start.
app.setName("knowtwin");

const APP_ROOT = path.join(__dirname, "..");
process.env.APP_ROOT = APP_ROOT;
const RENDERER_DIST = path.join(APP_ROOT, "dist");
const VITE_DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;
const IS_DEV = Boolean(VITE_DEV_SERVER_URL);

let win: BrowserWindow | null = null;

// Extensions the backend can ingest — single source of truth for both the dialog
// filters and the allowlist gate (defense-in-depth: never read a .env/.key/etc.).
const UPLOAD_DOC_EXT = ["pdf", "docx", "html", "htm", "md", "txt"];
// 'webm' included: in-app voice notes are recorded via MediaRecorder (webm/ogg).
const UPLOAD_AUDIO_EXT = ["mp3", "wav", "m4a", "ogg", "flac", "webm"];
// Fail fast before slurping a huge file into main memory.
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100 MB

// ── Content-Security-Policy ──────────────────────────────────────────────
// Prod is the exact policy from DESIGN.md §4 (no 'unsafe-eval'). Dev relaxes
// only what Vite HMR needs (ws: + 'unsafe-eval'), gated on VITE_DEV_SERVER_URL.
function cspFor(dev: boolean): string {
  if (dev) {
    return [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      "style-src 'self' 'unsafe-inline'",
      "connect-src 'self' ws://localhost:* http://localhost:*",
      "img-src 'self' data:",
      "font-src 'self' data:",
    ].join("; ");
  }
  // All API/WS traffic is opened by MAIN (the bridge), never by the renderer, so
  // connect-src only needs 'self' + the configured API origin as defense-in-depth.
  // Applied at boot; a URL change needs a restart to re-issue the policy.
  return [
    "default-src 'self'",
    "script-src 'self'",
    // style-src keeps 'unsafe-inline': the glass specular sets inline styles
    // (--mx/--my, gradients), same as EcoDB. base-uri/form-action locked to self.
    "style-src 'self' 'unsafe-inline'",
    "base-uri 'self'",
    "form-action 'self'",
    `connect-src 'self' ${getApiBase()}`,
    "img-src 'self' data:",
  ].join("; ");
}

function installSessionSecurity(): void {
  const csp = cspFor(IS_DEV);
  session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
    const headers = { ...details.responseHeaders };
    for (const k of Object.keys(headers)) {
      if (k.toLowerCase() === "content-security-policy") delete headers[k];
    }
    headers["Content-Security-Policy"] = [csp];
    cb({ responseHeaders: headers });
  });
  // Deny every permission request (camera, geolocation, notifications, …) — and
  // deny the synchronous permission *check* too, so nothing is silently granted.
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, done) => done(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
}

// ── IPC bridge handlers ──────────────────────────────────────────────────
// The key is read here (decryptApiKey) only to attach the Bearer header / the
// WS ?key. It never crosses to the renderer.
function registerIpc(): void {
  ipcMain.handle(
    "knowtwin:fetch",
    async (_e, args: { path: string; opts?: { method?: string; body?: unknown; headers?: Record<string, string> } }) => {
      // SSRF guard: the path must resolve to the API origin — never off-host.
      // Otherwise the Bearer key could be sent to an attacker.
      const target = resolveApiUrl(args.path, getApiBase());
      if (!target) return { ok: false, status: 400, data: null, error: "invalid_path" };
      const key = decryptApiKey();
      if (!key) return { ok: false, status: 401, data: null, error: "no_api_key" };
      try {
        const res = await fetch(target, {
          method: args.opts?.method ?? "GET",
          // Never follow a redirect: a 3xx to another origin would leak the
          // Bearer key off-host. Treat any 3xx as an error instead (VS1).
          redirect: "manual",
          headers: {
            "Content-Type": "application/json",
            ...(args.opts?.headers ?? {}),
            Authorization: `Bearer ${key}`,
          },
          body:
            args.opts?.body == null
              ? undefined
              : typeof args.opts.body === "string"
                ? args.opts.body
                : JSON.stringify(args.opts.body),
        });
        if (res.status >= 300 && res.status < 400) return { ok: false, status: res.status, data: null, error: "redirect" };
        const text = await res.text();
        let data: unknown = null;
        if (text) {
          try {
            data = JSON.parse(text);
          } catch {
            data = text;
          }
        }
        const result: { ok: boolean; status: number; data: unknown; retryAfter?: number } = {
          ok: res.ok,
          status: res.status,
          data,
        };
        if (res.status === 429) {
          const raw = res.headers.get("Retry-After");
          if (raw !== null) {
            const secs = Number(raw);
            if (Number.isFinite(secs) && secs > 0) result.retryAfter = secs;
          }
        }
        return result;
      } catch {
        return { ok: false, status: 0, data: null, error: "network" };
      }
    },
  );

  // ── WebSocket proxy (interview real-time, Spec §4.2) ──────────────────────
  // Main owns the connection: it opens ws://…/ws?key=<REAL_KEY> with the key
  // decrypted here, and forwards messages to the renderer over IPC. The key
  // never reaches the renderer (contrast with the old ws.ts that put it in the
  // URL from sessionStorage).
  const wsConns = new Map<string, WsClient>();

  ipcMain.handle("knowtwin:ws:connect", (e, args: { id: string; projectId: number; sessionId: string }) => {
    const channel = `knowtwin:ws:event:${args.id}`;
    const emit = (payload: { type: string; data: Record<string, unknown> }) => {
      if (!e.sender.isDestroyed()) e.sender.send(channel, payload);
    };
    const pid = Number(args.projectId);
    const sid = typeof args.sessionId === "string" ? args.sessionId : "";
    // Guard path segments: pid a positive integer, sid a safe token — no URL
    // injection into the origin (the ?key is appended after these).
    if (!Number.isInteger(pid) || pid <= 0 || !/^[A-Za-z0-9_-]+$/.test(sid)) {
      emit({ type: "error", data: { reason: "invalid_target" } });
      return;
    }
    const key = decryptApiKey();
    if (!key) {
      emit({ type: "error", data: { reason: "no_api_key" } });
      return;
    }
    // getApiBase() is a validated http/https origin (no path/query). http→ws,
    // https→wss (the 's' is preserved because 'https' → 'ws' + 's').
    const wsOrigin = getApiBase().replace(/^http/, "ws");
    const url = `${wsOrigin}/projects/${pid}/interviews/${encodeURIComponent(sid)}/ws?key=${encodeURIComponent(key)}`;
    let socket: WsClient;
    try {
      socket = new WsClient(url);
    } catch {
      emit({ type: "error", data: { reason: "ws_open_failed" } });
      return;
    }
    wsConns.set(args.id, socket);
    const onDestroyed = () => {
      try {
        socket.close();
      } catch {
        /* already closed */
      }
    };
    e.sender.once("destroyed", onDestroyed);
    socket.on("message", (raw: Buffer | ArrayBuffer | Buffer[]) => {
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(raw.toString());
      } catch {
        return;
      }
      if (parsed && typeof parsed === "object") {
        const obj = parsed as { type?: unknown; data?: unknown };
        emit({
          type: typeof obj.type === "string" ? obj.type : "message",
          data: obj.data && typeof obj.data === "object" ? (obj.data as Record<string, unknown>) : {},
        });
      }
    });
    socket.on("error", () => emit({ type: "error", data: { reason: "ws_error" } }));
    socket.on("close", () => {
      emit({ type: "close", data: {} });
      wsConns.delete(args.id);
      if (!e.sender.isDestroyed()) e.sender.removeListener("destroyed", onDestroyed);
    });
  });

  ipcMain.handle("knowtwin:ws:send", (_e, args: { id: string; data: string }) => {
    const s = wsConns.get(args.id);
    if (s && s.readyState === WsClient.OPEN) {
      s.send(typeof args.data === "string" ? args.data : JSON.stringify(args.data));
    }
  });

  ipcMain.handle("knowtwin:ws:close", (_e, args: { id: string }) => {
    const s = wsConns.get(args.id);
    if (s) {
      try {
        s.close();
      } catch {
        /* already closed */
      }
    }
    wsConns.delete(args.id);
  });

  // ── Key + config ──────────────────────────────────────────────────────────
  ipcMain.handle("knowtwin:setApiKey", (_e, key: unknown) => setApiKey(typeof key === "string" ? key : ""));
  ipcMain.handle("knowtwin:clearApiKey", () => {
    clearApiKey();
  });
  // Sync so the renderer can gate on it cheaply; returns a pure boolean.
  ipcMain.on("knowtwin:hasApiKey", (e) => {
    e.returnValue = hasApiKey();
  });

  // App config — the API base URL. Plain config (no secret). A change needs an
  // app restart to re-issue the CSP/connect-src for the new origin.
  ipcMain.handle("knowtwin:getConfig", () => ({ apiBaseUrl: getApiBase() }));
  ipcMain.handle("knowtwin:setConfig", (_e, cfg: { apiBaseUrl?: unknown }) => setApiBase(cfg?.apiBaseUrl));

  ipcMain.handle("knowtwin:saveFile", async (_e, args: { content: string; filename: string }) => {
    if (!win) return { ok: false, canceled: true };
    const r = await dialog.showSaveDialog(win, {
      defaultPath: args.filename,
      filters: [
        { name: "JSON", extensions: ["json"] },
        { name: "Text", extensions: ["txt"] },
        { name: "All Files", extensions: ["*"] },
      ],
    });
    if (r.canceled || !r.filePath) return { ok: false, canceled: true };
    await writeFile(r.filePath, args.content, "utf8");
    return { ok: true, path: r.filePath };
  });

  // ── Document upload ───────────────────────────────────────────────────────
  // The renderer reads the chosen File's bytes (arrayBuffer) and hands them here;
  // main validates ext + size, then POSTs multipart to the API with the Bearer
  // key. Bytes-through-main (not a host path, not a renderer fetch) keeps the key
  // in main AND preserves the renderer's file-input / in-app-recorder UX.
  ipcMain.handle(
    "knowtwin:uploadDocument",
    async (_e, args: { project_id?: number; visibility?: "public" | "private"; trust_hint?: string; filename?: string; bytes?: unknown }) => {
      const filename = typeof args?.filename === "string" ? path.basename(args.filename) : "";
      const ext = path.extname(filename).slice(1).toLowerCase();
      if (!filename || !UPLOAD_DOC_EXT.includes(ext)) return { ok: false, status: 0, data: null, error: "unsupported_type" };
      const buf = toBuffer(args?.bytes);
      if (!buf) return { ok: false, status: 0, data: null, error: "no_data" };
      if (buf.length > MAX_UPLOAD_BYTES) return { ok: false, status: 0, data: null, error: "file_too_large" };
      const pid = Number.isInteger(args?.project_id) ? (args.project_id as number) : 1;
      const vis = args?.visibility === "private" ? "private" : "public";
      // Flat path, project_id in QUERY (Hilo-confirmed EcoDB pattern).
      const qs = new URLSearchParams({ project_id: String(pid), visibility: vis });
      if (typeof args?.trust_hint === "string" && args.trust_hint) qs.set("trust_hint", args.trust_hint);
      const target = resolveApiUrl(`/documents/upload?${qs.toString()}`, getApiBase());
      if (!target) return { ok: false, status: 400, data: null, error: "invalid_path" };
      return postMultipart(target, buf, filename);
    },
  );

  // ── Voice upload (KnowTwin-specific — interview voice note) ────────────────
  // Same bytes-through-main flow, audio-only, POST /interviews/{sid}/voice.
  ipcMain.handle("knowtwin:uploadVoice", async (_e, args: { session_id?: string; filename?: string; bytes?: unknown }) => {
    const sid = typeof args?.session_id === "string" ? args.session_id : "";
    if (!/^[A-Za-z0-9_-]+$/.test(sid)) return { ok: false, status: 400, data: null, error: "invalid_session" };
    const filename = typeof args?.filename === "string" && args.filename ? path.basename(args.filename) : "voice.webm";
    const ext = path.extname(filename).slice(1).toLowerCase();
    if (!ext || !UPLOAD_AUDIO_EXT.includes(ext)) return { ok: false, status: 0, data: null, error: "unsupported_type" };
    const buf = toBuffer(args?.bytes);
    if (!buf) return { ok: false, status: 0, data: null, error: "no_data" };
    if (buf.length > MAX_UPLOAD_BYTES) return { ok: false, status: 0, data: null, error: "file_too_large" };
    const target = resolveApiUrl(`/interviews/${encodeURIComponent(sid)}/voice`, getApiBase());
    if (!target) return { ok: false, status: 400, data: null, error: "invalid_path" };
    return postMultipart(target, buf, filename);
  });
}

// Coerce an IPC-transferred ArrayBuffer / TypedArray into a Node Buffer, or null
// if it's neither (never trust the renderer to send the right shape).
function toBuffer(b: unknown): Buffer | null {
  if (b instanceof ArrayBuffer) return Buffer.from(b);
  if (ArrayBuffer.isView(b)) {
    const view = b as ArrayBufferView;
    return Buffer.from(view.buffer, view.byteOffset, view.byteLength);
  }
  return null;
}

// POST a byte buffer as multipart/form-data (field "file") to `target`,
// attaching the Bearer key. Shared by document + voice upload. Electron's
// main-process fetch does NOT reliably serialize a global FormData/Blob (the
// part comes through empty), so we build the body as a raw Buffer with an
// explicit boundary — works with any fetch impl.
async function postMultipart(
  target: URL,
  buf: Buffer,
  filename: string,
): Promise<{ ok: boolean; status?: number; data?: unknown; filename?: string; error?: string }> {
  const key = decryptApiKey();
  if (!key) return { ok: false, status: 401, data: null, error: "no_api_key" };
  try {
    const boundary = `----knowtwin${Date.now().toString(16)}`;
    const safeName = filename.replace(/["\r\n]/g, "_");
    const head = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${safeName}"\r\n` +
        `Content-Type: application/octet-stream\r\n\r\n`,
    );
    const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
    const body = Buffer.concat([head, buf, tail]);
    const res = await fetch(target, {
      method: "POST",
      // Never follow a redirect — the Bearer key must not travel off-origin (VS1).
      redirect: "manual",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": `multipart/form-data; boundary=${boundary}` },
      body,
    });
    if (res.status >= 300 && res.status < 400) return { ok: false, status: res.status, data: null, error: "redirect" };
    const text = await res.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    return { ok: res.ok, status: res.status, data, filename };
  } catch {
    return { ok: false, status: 0, data: null, error: "network" };
  }
}

// ── window ───────────────────────────────────────────────────────────────
function createWindow(): void {
  win = new BrowserWindow({
    width: 1380,
    height: 860,
    minWidth: 1280,
    minHeight: 720,
    show: false,
    ...(process.platform === "win32"
      ? { backgroundMaterial: "mica" as const, backgroundColor: "#00000000" }
      : { backgroundColor: "#ddd9d1" }),
    title: "KnowTwin",
    icon: path.join(APP_ROOT, "build", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      // Primary guard: DevTools cannot open at all in prod (the renderer holds
      // curated knowledge — claims, evidence, interviews — not for inspection).
      devTools: IS_DEV,
    },
  });

  win.once("ready-to-show", () => win?.show());

  // Surface renderer console (incl. any CSP violations) in the terminal — dev only.
  if (IS_DEV) {
    win.webContents.on("console-message", (_e, _level, message) => console.log("[renderer]", message));
  }

  // Defense-in-depth alongside devTools:false — if DevTools is ever re-enabled,
  // shut it immediately in prod.
  if (!IS_DEV) {
    win.webContents.on("devtools-opened", () => win?.webContents.closeDevTools());
  }

  // No popups, no external navigation.
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e, url) => {
    // SPA client-side routing uses the history API (no will-navigate). In prod
    // deny ALL navigation — a controlled file:// path could otherwise read local
    // files. In dev, allow only the vite dev origin (HMR full reloads).
    if (IS_DEV && VITE_DEV_SERVER_URL && url.startsWith(VITE_DEV_SERVER_URL)) return;
    e.preventDefault();
  });

  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(RENDERER_DIST, "index.html"));
  }
}

app.whenReady().then(() => {
  installSessionSecurity();
  registerIpc();
  createWindow();
});

app.on("window-all-closed", () => {
  win = null;
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
