// All API traffic goes through the main-process bridge (window.knowtwin.fetch),
// which owns the API key and attaches the Bearer header. The renderer never sees
// the key and never fetches the network directly (DESIGN.md §4). The public
// get/post/put/del contract is unchanged so callers/hooks are unaffected.

function bridge() {
  const b = window.knowtwin;
  if (!b) throw new Error("knowtwin bridge unavailable — run inside the Electron app");
  return b;
}

async function request<T>(path: string, opts?: { method?: string; body?: unknown }): Promise<T> {
  const res = await bridge().fetch<T>(path, opts);
  if (!res.ok) {
    const detail = typeof res.data === "string" ? res.data : res.data != null ? JSON.stringify(res.data) : "";
    throw new Error(`${res.status}: ${res.error ?? detail}`);
  }
  return res.data as T;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body });
}

export function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body });
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}
