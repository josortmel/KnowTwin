import { useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { NavRail } from "./NavRail";
import { AppBar } from "./AppBar";
import { SettingsDrawer } from "./SettingsDrawer";
import { Toasts } from "./Toasts";
import { CommandPalette } from "./CommandPalette";
import { SystemMonitor } from "./SystemMonitor";
import { ErrorBoundary } from "./ErrorBoundary";

// The shell for all views (DESIGN.md §3): glass nav rail + workzone (appbar +
// scrolling content + system monitor) floating over the backdrop. Desktop-first
// (Electron min 1280). ⌘K/Ctrl+K opens the command palette.
export function AppShell({ children }: { children: ReactNode }) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <div className="grid h-screen w-screen gap-[14px] overflow-hidden p-[14px]" style={{ gridTemplateColumns: "222px 1fr" }}>
        <NavRail onOpenSettings={() => setSettingsOpen(true)} settingsOpen={settingsOpen} />
        <div className="flex min-h-0 min-w-0 flex-col gap-[14px]">
          <AppBar />
          {/* Keyed by route so a view crash resets on navigation. */}
          <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-1 pb-4 pt-1.5">
            <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>
          </main>
          <SystemMonitor />
        </div>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Toasts />
    </>
  );
}
