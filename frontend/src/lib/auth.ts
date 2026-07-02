// Auth over the main-process bridge. The API key is stored encrypted in main
// (DPAPI/safeStorage) — the renderer can set/clear/query presence, but there is
// deliberately NO getApiKey: the raw key never enters the renderer (DESIGN.md §4).

function bridge() {
  return window.knowtwin ?? null;
}

export function hasApiKey(): boolean {
  return bridge()?.hasApiKey() ?? false;
}

export async function setApiKey(key: string): Promise<boolean> {
  const b = bridge();
  if (!b) return false;
  return b.setApiKey(key);
}

export async function clearApiKey(): Promise<void> {
  await bridge()?.clearApiKey();
}

export function isAuthenticated(): boolean {
  return hasApiKey();
}
