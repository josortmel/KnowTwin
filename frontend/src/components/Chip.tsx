import type { ReactNode } from "react";

// Mono micro-label (DESIGN.md §3). `tone: hot` tints it orange (signal); default
// is a quiet recessed chip.
interface ChipProps {
  children: ReactNode;
  tone?: "hot";
  className?: string;
}

export function Chip({ children, tone, className = "" }: ChipProps) {
  const style =
    tone === "hot"
      ? {
          background: "color-mix(in srgb, var(--accent) 16%, transparent)",
          boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 38%, transparent)",
        }
      : { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" };
  return (
    <span
      className={`inline-flex items-center rounded-sm px-[7px] py-[2px] font-mono text-[10px] tracking-[0.02em] ${
        tone === "hot" ? "text-ink-1" : "text-ink-2"
      } ${className}`}
      style={style}
    >
      {children}
    </span>
  );
}
