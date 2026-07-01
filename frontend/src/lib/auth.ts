const KEY = "knowtwin_api_key";

export function getApiKey(): string | null {
  return sessionStorage.getItem(KEY);
}

export function setApiKey(key: string): void {
  sessionStorage.setItem(KEY, key);
}

export function clearApiKey(): void {
  sessionStorage.removeItem(KEY);
}

export function isAuthenticated(): boolean {
  return getApiKey() !== null;
}
