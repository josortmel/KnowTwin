import { Badge } from "./Badge";

// Dispute state (DESIGN.md §7.3) — dot + ink. `undisputed` renders NOTHING
// (default, don't add noise).
const MAP: Record<string, { color: string; label: string }> = {
  disputed: { color: "var(--disp-disputed)", label: "Contradiction" },
  resolved_in_favor: { color: "var(--disp-resolved-for)", label: "Resolved (kept)" },
  resolved_against: { color: "var(--disp-resolved-against)", label: "Resolved (dropped)" },
};

export function DisputeBadge({ state, className = "" }: { state: string; className?: string }) {
  if (!state || state === "undisputed") return null;
  const m = MAP[state] ?? { color: "var(--ink-4)", label: state.replace(/_/g, " ") };
  return <Badge color={m.color} label={m.label} className={className} />;
}
