import { Dot } from "./Dot";

// Base for the KnowTwin domain-badge family (DESIGN.md §7). ALWAYS dot + ink
// label, mono — NEVER colored text (§1.3 norm). The color is a CSS var that
// only tints the dot; the label stays --ink-2. All §7 badges build on this so
// the norm can't be bypassed per-badge.
interface BadgeProps {
  color: string;
  label: string;
  glow?: boolean;
  className?: string;
}

export function Badge({ color, label, glow, className = "" }: BadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <Dot color={color} glow={glow} size={6} />
      <span className="font-mono text-[10px] leading-none tracking-[0.02em] text-ink-2">{label}</span>
    </span>
  );
}
