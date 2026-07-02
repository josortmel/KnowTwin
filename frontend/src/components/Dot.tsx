import type { CSSProperties } from "react";

// Indicator dot (DESIGN.md §3). Semantic `s` picks a signal color; `color` (a CSS
// var/string) overrides for domain states (§7). Glow is reserved for signal
// (on/ok/alert) — idle and quiet domain dots carry none. `anim` blinks (active
// session) or pulses; both stop under prefers-reduced-motion.
export type DotState = "on" | "ok" | "alert" | "idle";
export type DotAnim = "none" | "pulse" | "blink";

const STATE_COLOR: Record<DotState, string> = {
  on: "var(--accent)",
  ok: "var(--grn)",
  alert: "var(--red)",
  idle: "var(--ink-4)",
};

const SIGNAL: DotState[] = ["on", "ok", "alert"];

interface DotProps {
  s?: DotState;
  /** Domain color (a CSS var like `var(--claim-single)`) — overrides `s`. */
  color?: string;
  anim?: DotAnim;
  /** Force glow on/off. Defaults: on for signal states, off otherwise. */
  glow?: boolean;
  size?: number;
  className?: string;
}

export function Dot({ s = "idle", color, anim = "none", glow, size = 7, className = "" }: DotProps) {
  const fill = color ?? STATE_COLOR[s];
  const showGlow = glow ?? (!color && SIGNAL.includes(s));
  const animClass =
    anim === "blink"
      ? "animate-blink motion-reduce:animate-none"
      : anim === "pulse"
        ? "animate-pulse motion-reduce:animate-none"
        : "";
  const style: CSSProperties = {
    width: size,
    height: size,
    background: fill,
    boxShadow: showGlow ? `0 0 6px ${fill}` : undefined,
  };
  return <span className={`inline-block flex-none rounded-full ${animClass} ${className}`} style={style} />;
}
