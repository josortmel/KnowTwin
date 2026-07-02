import { useEffect, useState } from "react";
import { BrandLockup } from "./BrandMark";
import { StatusPill } from "./StatusPill";
import { ThemeToggle } from "./ThemeToggle";
import { useHealth } from "../hooks/useHealth";

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const time = now.toLocaleTimeString("en-US", { hour12: false });
  const date = now.toLocaleDateString("en-US", { weekday: "short", day: "2-digit", month: "short" });
  return (
    <div className="flex flex-col gap-0.5 text-right font-mono text-[11px] leading-none text-ink-3">
      <span className="tabular-nums tracking-[0.04em]">{time}</span>
      <span className="text-ink-2">{date}</span>
    </div>
  );
}

// Floating glass tray across the top of the workzone (DESIGN.md §3 chrome).
// Brand + wordmark on the left; API health, clock, theme on the right.
export function AppBar() {
  const status = useHealth();
  return (
    <header
      className="flex flex-none items-center gap-4 overflow-hidden rounded-xl px-6 py-4"
      style={{
        background: "var(--tray-bg)",
        backdropFilter: "blur(22px) saturate(1.3)",
        WebkitBackdropFilter: "blur(22px) saturate(1.3)",
        boxShadow: "var(--tray-shadow)",
      }}
    >
      <BrandLockup size={22} />
      <div className="flex-1" />
      <StatusPill status={status} />
      <Clock />
      <ThemeToggle />
    </header>
  );
}
