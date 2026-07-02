import { GlassCard } from "./GlassCard";
import { Dot } from "./Dot";

interface StatCardProps {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  accent?: boolean;
  loading?: boolean;
  error?: boolean;
  onClick?: () => void;
  tooltip?: string;
}

// Condensed stat (DESIGN.md §3). Renders a <button> only when it navigates;
// otherwise a plain <div> (a11y — no inert button affordance).
export function StatCard({ label, value, unit, sub, accent, loading, error, onClick, tooltip }: StatCardProps) {
  const inner = (
    <>
      {/* §1.3 norm: signal via a dot beside the label — NEVER by coloring the
          value text (low-L accent can't reach 4.5:1 on the light card). */}
      <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">
        {label}
        {accent && !error && <Dot s="on" size={5} />}
      </span>
      {loading ? (
        <span className="mt-0.5 h-[22px] w-3/5 animate-pulse rounded-sm motion-reduce:animate-none" style={{ background: "var(--inset)" }} />
      ) : (
        <span className="font-mono text-[22px] font-medium leading-none tabular-nums text-ink-1">
          {error ? "—" : value}
          {unit && !error && <span className="ml-0.5 text-[12px] text-ink-3">{unit}</span>}
        </span>
      )}
      {sub && <span className="truncate font-mono text-[10px] text-ink-3">{error ? "unavailable" : sub}</span>}
    </>
  );

  return (
    <GlassCard className="p-4">
      {onClick ? (
        <button type="button" onClick={onClick} title={tooltip} className="flex w-full flex-col gap-1.5 text-left">
          {inner}
        </button>
      ) : (
        <div title={tooltip} className={`flex w-full flex-col gap-1.5 ${tooltip ? "cursor-help" : ""}`}>
          {inner}
        </div>
      )}
    </GlassCard>
  );
}
