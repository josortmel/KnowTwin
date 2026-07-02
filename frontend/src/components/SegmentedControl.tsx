// Segmented control (DESIGN.md §3): recessed track, active segment raised. Mono
// labels. Used e.g. for the claim filter (All / Pending / Draft / Disputed).
interface SegmentedControlProps {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
}

export function SegmentedControl({ options, value, onChange, ariaLabel }: SegmentedControlProps) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex items-center gap-0.5 rounded-md p-0.5"
      style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={`rounded-[7px] px-2.5 py-1 font-mono text-[11px] transition-colors ${
              active ? "font-semibold text-ink-1" : "text-ink-3 hover:text-ink-1"
            }`}
            style={active ? { background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline), 0 1px 2px rgba(0,0,0,0.1)" } : undefined}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
