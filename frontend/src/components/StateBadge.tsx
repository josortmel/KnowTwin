import { Badge } from "./Badge";

// Generic status badge (dot + ink, DESIGN.md §1.3 norm). Used for document /
// process status. For claim epistemics use the §7 badges (Corroboration,
// Coverage, Dispute, TrustTier, Sensitivity) instead.
const MAP: Record<string, string> = {
  // ready / positive
  indexed: "var(--grn)",
  ready: "var(--grn)",
  ok: "var(--grn)",
  done: "var(--grn)",
  complete: "var(--grn)",
  active: "var(--grn)",
  // in-progress (amber)
  processing: "var(--cov-partial)",
  pending: "var(--cov-partial)",
  queued: "var(--cov-partial)",
  partial: "var(--cov-partial)",
  // negative
  failed: "var(--red)",
  error: "var(--red)",
  // neutral
  duplicate: "var(--ink-3)",
  skipped: "var(--ink-3)",
  stale: "var(--ink-3)",
  draft: "var(--ink-4)",
  // signal
  disputed: "var(--accent)",
};

export function StateBadge({ state, className = "" }: { state: string; className?: string }) {
  const color = MAP[state] ?? "var(--ink-4)";
  return <Badge color={color} label={state.replace(/_/g, " ")} className={className} />;
}
