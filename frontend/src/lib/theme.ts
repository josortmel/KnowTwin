import { useSyncExternalStore } from "react";

// Theme is stored as `data-theme` on <html> (the tokens.css selector) and
// persisted to localStorage. No zustand — a tiny external store keeps the
// ThemeToggle in sync across the app without a dependency.
export type Theme = "light" | "dark";

const STORAGE_KEY = "knowtwin-theme";

function current(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "dark" ? "dark" : "light";
}

const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function setTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* private mode / storage disabled — theme still applies for the session */
  }
  emit();
}

export function toggleTheme(): void {
  setTheme(current() === "light" ? "dark" : "light");
}

// Note: the persisted theme is applied pre-paint by public/theme-init.js (a
// blocking <head> script), so there's no runtime init step here — useTheme just
// reads the attribute it already set.

export function useTheme(): Theme {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    current,
    () => "light" as Theme,
  );
}
