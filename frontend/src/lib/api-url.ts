// Resolve a renderer-supplied path against the configured API origin, rejecting
// anything that could redirect the request (and the Bearer key) off-origin.
// Building the URL by string concatenation (`base + path`) is the bug being
// fixed: a path like '@evil.com/x' yields 'http://localhost:8090@evil.com/x',
// whose host is evil.com. Using `new URL(path, base)` + an origin check defeats
// that, plus protocol-relative '//evil.com' and the backslash variant
// '/\\evil.com'. `base` is the configured API URL (config-store.getApiBase in
// main; tests pass it explicitly) so this module stays free of electron deps.
export function resolveApiUrl(path: unknown, base: string): URL | null {
  if (typeof path !== "string" || !path.startsWith("/")) return null;
  try {
    const url = new URL(path, base);
    return url.origin === new URL(base).origin ? url : null;
  } catch {
    return null;
  }
}
