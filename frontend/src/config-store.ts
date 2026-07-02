// MAIN-PROCESS ONLY. Plain (non-encrypted) app config — currently the API base
// URL. Unlike the API key (secure-store, DPAPI-encrypted), this holds no secret,
// so a normal electron-store file is fine.
import Store from "electron-store";

export const DEFAULT_API_BASE = "http://localhost:8090";

// Lazy — created after app.setName() so the userData path is stable (same reason
// as secure-store). Both stores must resolve to the same userData dir.
let _store: Store<{ apiBaseUrl?: string }> | null = null;
function store(): Store<{ apiBaseUrl?: string }> {
  return (_store ??= new Store<{ apiBaseUrl?: string }>({ name: "knowtwin-config" }));
}

// Validate + normalize to an origin: http/https only, a host, optional port.
// Drops any path/query and rejects file:/javascript:/etc. Returns null if invalid.
export function normalizeApiBase(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const s = raw.trim();
  if (!s) return null;
  try {
    const u = new URL(s);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    if (!u.hostname) return null;
    // VS2: plaintext http:// only for loopback. Any non-loopback host must be
    // https — a remote http origin would carry the Bearer key in the clear.
    const host = u.hostname.toLowerCase();
    const isLoopback = host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "[::1]";
    if (u.protocol === "http:" && !isLoopback) return null;
    return u.origin;
  } catch {
    return null;
  }
}

export function getApiBase(): string {
  const v = store().get("apiBaseUrl");
  return typeof v === "string" && v ? v : DEFAULT_API_BASE;
}

export function setApiBase(raw: unknown): { ok: boolean; error?: string } {
  const origin = normalizeApiBase(raw);
  if (!origin) return { ok: false, error: "invalid_url" };
  store().set("apiBaseUrl", origin);
  return { ok: true };
}
