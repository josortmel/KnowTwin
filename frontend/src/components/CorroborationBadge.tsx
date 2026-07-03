import { Badge } from "./Badge";

// Verification status (§7.1) — the knowledge trust ladder, dot + ink. HR-facing
// vocabulary (codes stay as-is on the wire).
const MAP: Record<string, { color: string; label: string }> = {
  draft: { color: "var(--claim-draft)", label: "Draft" },
  single_source: { color: "var(--claim-single)", label: "Unverified" },
  corroborated: { color: "var(--claim-corroborated)", label: "Verified" },
  corroborated_by_employee: { color: "var(--claim-corroborated-employee)", label: "Confirmed by employee" },
  validated: { color: "var(--claim-validated)", label: "Fully verified" },
  rejected: { color: "var(--claim-rejected)", label: "Rejected" },
};

export function CorroborationBadge({ level, className = "" }: { level: string; className?: string }) {
  const m = MAP[level] ?? { color: "var(--ink-4)", label: level.replace(/_/g, " ") };
  return <Badge color={m.color} label={m.label} className={className} />;
}
