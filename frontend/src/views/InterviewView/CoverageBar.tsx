import { useEffect, useState } from "react";

interface CoverageBarProps {
  initialPct: number;
  entityCount: number;
  onWsUpdate?: (pct: number) => void;
  wsPct?: number | null;
}

export function CoverageBar({ initialPct, entityCount, wsPct }: CoverageBarProps) {
  const [pct, setPct] = useState(initialPct);

  useEffect(() => {
    if (wsPct != null) setPct(wsPct);
  }, [wsPct]);

  return (
    <div className="w-full">
      <div className="mb-1 flex justify-between font-mono text-[11px] text-ink-2">
        <span className="uppercase tracking-[0.1em] text-ink-3">Coverage</span>
        <span className="tabular-nums">
          {pct.toFixed(1)}% of {entityCount} areas
        </span>
      </div>
      {/* Monochrome graphite bar (§5) — coverage is data, not signal. */}
      <div className="h-3 w-full overflow-hidden rounded-full" style={{ background: "var(--inset)" }}>
        <div
          className="h-full rounded-full transition-all duration-700 ease-out motion-reduce:transition-none"
          style={{ width: `${Math.min(pct, 100)}%`, background: "var(--chart-bar)" }}
        />
      </div>
    </div>
  );
}
