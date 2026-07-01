/**
 * Sanitize text for safe display. Returns plain text — no HTML.
 * NEVER use dangerouslySetInnerHTML anywhere in this codebase.
 */
export function safeText(input: unknown): string {
  if (input === null || input === undefined) return "";
  return String(input);
}
