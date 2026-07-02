import { Badge } from "./Badge";

// Coverage state (DESIGN.md §7.2) — entity knowledge completeness, dot + ink.
const MAP: Record<string, { color: string; label: string }> = {
  unknown: { color: "var(--cov-unknown)", label: "Unknown" },
  partial: { color: "var(--cov-partial)", label: "Partial" },
  clear: { color: "var(--cov-clear)", label: "Clear" },
  disputed: { color: "var(--cov-disputed)", label: "Disputed" },
  validated: { color: "var(--cov-validated)", label: "Validated" },
  stale: { color: "var(--cov-stale)", label: "Stale" },
};

export function CoverageStateBadge({ state, className = "" }: { state: string; className?: string }) {
  const m = MAP[state] ?? { color: "var(--ink-4)", label: state.replace(/_/g, " ") };
  return <Badge color={m.color} label={m.label} className={className} />;
}
