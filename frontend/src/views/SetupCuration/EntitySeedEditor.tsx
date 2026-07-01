import { useQuery } from "@tanstack/react-query";
import { get } from "../../lib/api";
import { SafeText } from "../../components/SafeText";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";

interface EntityExpected {
  entity_name: string;
  entity_type: string;
  expected_count: number;
  coverage_pct: number;
  coverage_state: string;
}

interface Props { projectId: number }

export function EntitySeedEditor({ projectId }: Props) {
  const { data, isLoading, error } = useQuery<{ entities: EntityExpected[] }>({
    queryKey: ["entities", projectId],
    queryFn: () => get(`/graph/entities?project_id=${projectId}`),
    enabled: projectId > 0,
  });

  return (
    <div className="border rounded p-4">
      <h3 className="font-semibold mb-1">Entity Dictionary</h3>
      <p className="text-xs text-gray-400 mb-3">Read-only in MVP</p>
      {isLoading && <Loading />}
      {error && <p className="text-red-500 text-sm">{String(error)}</p>}
      {data && data.entities.length === 0 && <EmptyState message="No entities seeded" />}
      {data && data.entities.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-gray-500 border-b">
            <th className="py-1">Entity</th><th>Type</th><th>Coverage</th>
          </tr></thead>
          <tbody>
            {data.entities.map(e => (
              <tr key={e.entity_name} className="border-b">
                <td className="py-1"><SafeText text={e.entity_name} /></td>
                <td><SafeText text={e.entity_type} /></td>
                <td className="text-gray-500">{e.coverage_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
