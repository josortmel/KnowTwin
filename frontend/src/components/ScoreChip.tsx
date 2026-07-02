import type { ScoreComponents } from "../hooks/useScore";

interface ScoreChipProps {
  score: number;
  components: ScoreComponents;
  claimCount: number;
}

// §7.6 process framing — labels describe the PROCESS (knowledge capture), never
// the person. No ranking / performance language.
const COMPONENT_LABELS: { key: keyof ScoreComponents; label: string }[] = [
  { key: "coverage_contrib", label: "Coverage contribution" },
  { key: "contradiction_yield", label: "Contradiction yield" },
  { key: "quality", label: "Quality" },
  { key: "gaming_penalty", label: "Gaming penalty" },
];

// Score is DATA, not signal (§5 monochrome): the value is graphite --ink-1,
// never a colored fill. Hover reveals the component breakdown.
export function ScoreChip({ score, components, claimCount }: ScoreChipProps) {
  return (
    <div
      className="group relative inline-flex items-center gap-2 rounded-md px-2.5 py-1"
      style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
    >
      <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">Completeness</span>
      <span className="font-mono text-[15px] font-medium leading-none tabular-nums text-ink-1">{Math.round(score)}</span>

      <div
        role="tooltip"
        className="pointer-events-none absolute right-0 top-full z-[70] mt-2 hidden w-72 rounded-md p-3 group-hover:block"
        style={{
          background: "var(--card-bg)",
          boxShadow: "var(--elev)",
          backdropFilter: "blur(14px) saturate(1.4)",
          WebkitBackdropFilter: "blur(14px) saturate(1.4)",
        }}
      >
        <div className="mb-2 font-body text-[11px] leading-relaxed text-ink-2">
          Knowledge capture completeness — process signals, not a personal ranking.
        </div>
        <div className="flex flex-col gap-1">
          {COMPONENT_LABELS.map(({ key, label }) => (
            <div key={key} className="flex items-center justify-between gap-3">
              <span className="font-body text-[12px] text-ink-2">{label}</span>
              <span className="font-mono text-[12px] tabular-nums text-ink-1">{components[key]}</span>
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center justify-between border-t pt-2" style={{ borderColor: "var(--card-hairline)" }}>
          <span className="font-body text-[12px] text-ink-2">Claims captured</span>
          <span className="font-mono text-[12px] tabular-nums text-ink-1">{claimCount}</span>
        </div>
      </div>
    </div>
  );
}
