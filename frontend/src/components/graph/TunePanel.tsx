import { GlassCard } from "../GlassCard";

// Active (filled) track = soft green slightly darker than --sec-graph for depth;
// empty track = recessed neutral.
const FILL = "color-mix(in srgb, var(--sec-graph) 82%, #000 18%)";
const EMPTY = "var(--inset)";

function Slider({ label, value, min, max, step, onChange, fmt }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt: (v: number) => string }) {
  const pct = Math.round(((value - min) / (max - min)) * 100);
  return (
    <label className="flex flex-col gap-1">
      <div className="flex items-center justify-between font-mono text-[9.5px] text-ink-2">
        <span className="uppercase tracking-[0.08em] opacity-80">{label}</span>
        <span className="tabular-nums opacity-90">{fmt(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
        className="h-[14px] w-full cursor-pointer appearance-none rounded-full"
        style={{
          accentColor: "var(--sec-graph)",
          background: `linear-gradient(to right, ${FILL} 0%, ${FILL} ${pct}%, ${EMPTY} ${pct}%, ${EMPTY} 100%)`,
          boxShadow: "inset 0 1px 2px rgba(0,0,0,0.55)",
        }}
      />
    </label>
  );
}

export interface TuneValues {
  charge: number;
  linkDist: number;
  nodeSize: number;
  labelZoom: number;
}

export interface TunePanelProps {
  open: boolean;
  onToggle: () => void;
  values: TuneValues;
  onChange: (patch: Partial<TuneValues>) => void;
}

export function TunePanel({ open, onToggle, values, onChange }: TunePanelProps) {
  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-mono text-[9.5px] uppercase tracking-[0.1em] transition-colors"
        style={{ background: "rgba(10,10,12,0.5)", color: "var(--screen-text)", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} width={12} height={12} aria-hidden="true">
          <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4" strokeLinecap="round" />
          <circle cx="16" cy="6" r="2" />
          <circle cx="8" cy="12" r="2" />
          <circle cx="14" cy="18" r="2" />
        </svg>
        Tune
      </button>
      {open && (
        <GlassCard className="w-[190px] p-3">
          <div className="flex flex-col gap-3">
            <Slider label="Repel" value={values.charge} min={-400} max={-10} step={5} onChange={(v) => onChange({ charge: v })} fmt={(v) => String(Math.round(-v))} />
            <Slider label="Link dist" value={values.linkDist} min={10} max={220} step={5} onChange={(v) => onChange({ linkDist: v })} fmt={(v) => String(Math.round(v))} />
            <Slider label="Node size" value={values.nodeSize} min={0.5} max={2.5} step={0.1} onChange={(v) => onChange({ nodeSize: v })} fmt={(v) => `${v.toFixed(1)}×`} />
            <Slider label="Label zoom" value={values.labelZoom} min={0.8} max={3} step={0.1} onChange={(v) => onChange({ labelZoom: v })} fmt={(v) => v.toFixed(1)} />
          </div>
        </GlassCard>
      )}
    </div>
  );
}
