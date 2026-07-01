import { useCoverage } from "../../hooks/useCoverage";
import { SafeText } from "../../components/SafeText";
import { StateBadge } from "../../components/StateBadge";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";

interface Props { projectId: number }

export function CoverageDashboard({ projectId }: Props) {
  const { data, isLoading, error } = useCoverage(projectId);

  return (
    <div className="border rounded p-4">
      <h3 className="font-semibold mb-3">Coverage</h3>
      {isLoading && <Loading />}
      {error && <p className="text-red-500 text-sm">{String(error)}</p>}
      {data && (
        <>
          <div className="mb-3">
            <div className="flex justify-between text-sm mb-1">
              <span>Overall coverage</span>
              <span className="font-mono">{data.overall_coverage_pct}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-3">
              <div className="bg-blue-600 h-3 rounded-full transition-all"
                style={{ width: `${Math.min(data.overall_coverage_pct, 100)}%` }} />
            </div>
            <p className="text-xs text-gray-400 mt-1">{data.entity_count} entities tracked</p>
          </div>
          {data.entities.length === 0 && <EmptyState message="No coverage data" />}
          {data.entities.length > 0 && (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-gray-500 border-b">
                <th className="py-1">Entity</th><th>Type</th><th>Coverage</th><th>State</th>
              </tr></thead>
              <tbody>
                {data.entities.map(e => (
                  <tr key={e.entity_name} className="border-b">
                    <td className="py-1"><SafeText text={e.entity_name} /></td>
                    <td className="text-gray-500"><SafeText text={e.entity_type} /></td>
                    <td className="font-mono">{e.coverage_pct}%</td>
                    <td><StateBadge state={e.coverage_state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
