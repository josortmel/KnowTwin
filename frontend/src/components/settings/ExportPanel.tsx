import { useState } from "react";
import { exportClaimLedger, exportGraphDump, exportVerifiedDoc } from "../../hooks/useExport";

interface Props {
  projectId: number;
}

const EXPORTS: { fn: (id: number) => Promise<void>; key: string; label: string }[] = [
  { fn: exportVerifiedDoc, key: "doc", label: "Verified Document (Markdown)" },
  { fn: exportClaimLedger, key: "claims", label: "Claim Ledger (CSV)" },
  { fn: exportGraphDump, key: "graph", label: "Graph Entity Dump (CSV)" },
];

export function ExportPanel({ projectId }: Props) {
  const [loading, setLoading] = useState<string | null>(null);

  const handleExport = async (fn: (id: number) => Promise<void>, key: string) => {
    setLoading(key);
    try {
      await fn(projectId);
    } catch (e) {
      console.error("Export failed:", e);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div>
      <div className="space-y-2">
        {EXPORTS.map((x) => (
          <button
            key={x.key}
            type="button"
            onClick={() => handleExport(x.fn, x.key)}
            disabled={loading !== null}
            className="w-full rounded-md px-3 py-2 text-left font-mono text-[11px] text-ink-1 transition-[filter] hover:brightness-[0.98] disabled:opacity-50"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          >
            {loading === x.key ? "Exporting…" : x.label}
          </button>
        ))}
      </div>
      <p className="mt-2 font-mono text-[10px] text-ink-3">CSV exports are formula-injection safe.</p>
    </div>
  );
}
