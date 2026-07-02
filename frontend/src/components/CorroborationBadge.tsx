import { Badge } from "./Badge";

// Corroboration level (DESIGN.md §7.1) — the claim trust ladder, dot + ink.
const MAP: Record<string, { color: string; label: string }> = {
  draft: { color: "var(--claim-draft)", label: "Draft" },
  single_source: { color: "var(--claim-single)", label: "Single source" },
  corroborated: { color: "var(--claim-corroborated)", label: "Corroborated" },
  corroborated_by_employee: { color: "var(--claim-corroborated-employee)", label: "Employee-confirmed" },
  validated: { color: "var(--claim-validated)", label: "Validated" },
  rejected: { color: "var(--claim-rejected)", label: "Rejected" },
};

export function CorroborationBadge({ level, className = "" }: { level: string; className?: string }) {
  const m = MAP[level] ?? { color: "var(--ink-4)", label: level.replace(/_/g, " ") };
  return <Badge color={m.color} label={m.label} className={className} />;
}
