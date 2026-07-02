import { Badge } from "./Badge";

// Sensitivity (DESIGN.md §7.4) — disclosure scope, dot + ink. Interview claims
// default to `restricted` so nothing tacit leaks by omission.
const MAP: Record<string, { color: string; label: string }> = {
  public: { color: "var(--sens-public)", label: "Public" },
  team: { color: "var(--sens-team)", label: "Team" },
  restricted: { color: "var(--sens-restricted)", label: "Restricted" },
};

export function SensitivityBadge({ level, className = "" }: { level: string; className?: string }) {
  const m = MAP[level] ?? { color: "var(--ink-4)", label: level.replace(/_/g, " ") };
  return <Badge color={m.color} label={m.label} className={className} />;
}
