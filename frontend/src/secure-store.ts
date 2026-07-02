// MAIN-PROCESS ONLY. Never import from the renderer.
//
// The API key is stored on disk encrypted with the OS keychain (safeStorage,
// DPAPI on Windows) — never as plaintext. `decryptApiKey` is internal to main
// and is the ONLY place the key is materialized; it is used solely to attach
// the Bearer header inside the fetch/sse/ws handlers. It is never exposed over
// the contextBridge. The key (and its ciphertext) is never logged.
import Store from "electron-store";
import { safeStorage } from "electron";

const KEY = "api_key_encrypted"; // value = base64(safeStorage ciphertext)

// Lazy instantiation: the Store must be created AFTER app.setName() runs in
// main.ts. electron-store derives its file path from app.getName(); if it were
// created at import time (before setName), the userData dir — and this very file
// — could land under "Electron" on one launch and the real app name on another,
// so the persisted key wouldn't be found on the next start.
//
// No `encryptionKey` option — that would be a static bundle-embedded key
// (decompile the .exe → decrypt config.json). The OS keychain via safeStorage
// is the only thing protecting the key at rest.
let _store: Store<{ api_key_encrypted?: string }> | null = null;
function store(): Store<{ api_key_encrypted?: string }> {
  return (_store ??= new Store<{ api_key_encrypted?: string }>({ name: "knowtwin-secure" }));
}

export function hasApiKey(): boolean {
  const enc = store().get(KEY);
  return typeof enc === "string" && enc.length > 0;
}

export function setApiKey(raw: string): boolean {
  const key = typeof raw === "string" ? raw.trim() : "";
  if (!key) return false;
  if (key.length > 512) return false; // bound the ciphertext/write size
  if (!safeStorage.isEncryptionAvailable()) {
    // Refuse to persist a plaintext key. The auth screen surfaces this.
    throw new Error("encryption_unavailable");
  }
  const ciphertext = safeStorage.encryptString(key).toString("base64");
  store().set(KEY, ciphertext);
  return true;
}

export function clearApiKey(): void {
  store().delete(KEY);
}

/** Internal to main. Returns the decrypted key or null. Never exposed. */
export function decryptApiKey(): string | null {
  const enc = store().get(KEY);
  if (typeof enc !== "string" || !enc) return null;
  try {
    return safeStorage.decryptString(Buffer.from(enc, "base64"));
  } catch {
    return null;
  }
}
