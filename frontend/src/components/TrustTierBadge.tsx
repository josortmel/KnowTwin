import { Badge } from "./Badge";

// Trust tier (DESIGN.md §7.4) — source strength, dot + ink.
const MAP: Record<number, { color: string; label: string }> = {
  0: { color: "var(--trust-0)", label: "Inferred" },
  1: { color: "var(--trust-1)", label: "Documentary" },
  2: { color: "var(--trust-2)", label: "Formal" },
};

export function TrustTierBadge({ tier, className = "" }: { tier: number; className?: string }) {
  const m = MAP[tier] ?? { color: "var(--ink-4)", label: `Tier ${tier}` };
  return <Badge color={m.color} label={m.label} className={className} />;
}
