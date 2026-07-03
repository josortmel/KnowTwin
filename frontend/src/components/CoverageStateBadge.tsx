import { Badge } from "./Badge";

// Knowledge completeness (§7.2) — per person/system/project, dot + ink. HR-facing.
const MAP: Record<string, { color: string; label: string }> = {
  unknown: { color: "var(--cov-unknown)", label: "Not captured" },
  partial: { color: "var(--cov-partial)", label: "In progress" },
  clear: { color: "var(--cov-clear)", label: "Captured" },
  disputed: { color: "var(--cov-disputed)", label: "Contradiction" },
  validated: { color: "var(--cov-validated)", label: "Verified" },
  stale: { color: "var(--cov-stale)", label: "Needs refresh" },
};

export function CoverageStateBadge({ state, className = "" }: { state: string; className?: string }) {
  const m = MAP[state] ?? { color: "var(--ink-4)", label: state.replace(/_/g, " ") };
  return <Badge color={m.color} label={m.label} className={className} />;
}
