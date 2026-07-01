import { useState } from "react";
import { exportClaimLedger, exportGraphDump, exportVerifiedDoc } from "../../hooks/useExport";

interface Props {
  projectId: number;
}

export function ExportPanel({ projectId }: Props) {
  const [loading, setLoading] = useState<string | null>(null);

  const handleExport = async (fn: (id: number) => Promise<void>, label: string) => {
    setLoading(label);
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
      <h3 className="text-sm font-semibold mb-2">Export Data</h3>
      <div className="space-y-2">
        <button
          onClick={() => handleExport(exportVerifiedDoc, "doc")}
          disabled={loading !== null}
          className="w-full text-left border rounded px-3 py-2 text-xs hover:bg-gray-50 disabled:opacity-50"
        >
          {loading === "doc" ? "Exporting..." : "Verified Document (Markdown)"}
        </button>
        <button
          onClick={() => handleExport(exportClaimLedger, "claims")}
          disabled={loading !== null}
          className="w-full text-left border rounded px-3 py-2 text-xs hover:bg-gray-50 disabled:opacity-50"
        >
          {loading === "claims" ? "Exporting..." : "Claim Ledger (CSV)"}
        </button>
        <button
          onClick={() => handleExport(exportGraphDump, "graph")}
          disabled={loading !== null}
          className="w-full text-left border rounded px-3 py-2 text-xs hover:bg-gray-50 disabled:opacity-50"
        >
          {loading === "graph" ? "Exporting..." : "Graph Entity Dump (CSV)"}
        </button>
      </div>
      <p className="text-xs text-gray-400 mt-2">
        CSV exports are formula-injection safe.
      </p>
    </div>
  );
}
