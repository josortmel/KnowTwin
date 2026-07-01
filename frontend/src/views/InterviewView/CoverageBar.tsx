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
      <div className="flex justify-between text-sm text-gray-600 mb-1">
        <span>Coverage</span>
        <span>{pct.toFixed(1)}% of {entityCount} areas</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
        <div
          className="bg-blue-500 h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}
