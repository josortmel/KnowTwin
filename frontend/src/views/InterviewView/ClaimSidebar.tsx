import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { del, get } from "../../lib/api";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { Loading } from "../../components/Loading";

interface Claim {
  id: string;
  subject_entity: string;
  predicate: string;
  evidence_text: string;
  corroboration_level: string;
}

interface ClaimSidebarProps {
  sessionId: string;
  claimIds: string[];
}

export function ClaimSidebar({ sessionId, claimIds }: ClaimSidebarProps) {
  const qc = useQueryClient();
  const { data: claims, isLoading } = useQuery<Claim[]>({
    queryKey: ["session-claims", sessionId, claimIds.length],
    queryFn: async () => {
      if (!claimIds.length) return [];
      const results: Claim[] = [];
      for (const id of claimIds.slice(-20)) {
        try {
          const c = await get<Claim>(`/claims/${id}`);
          results.push(c);
        } catch { /* claim may not be accessible */ }
      }
      return results;
    },
    enabled: claimIds.length > 0,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => del(`/claims/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-claims"] }),
  });

  if (isLoading) return <Loading />;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-700">Claims this session ({claimIds.length})</h3>
      {(!claims || claims.length === 0) && (
        <p className="text-sm text-gray-400">No claims yet</p>
      )}
      {claims?.map((c) => (
        <div key={c.id} className="p-2 bg-white rounded border text-sm space-y-1">
          <div className="flex items-center justify-between">
            <SafeText text={`${c.subject_entity} — ${c.predicate}`} className="font-medium text-gray-800 text-xs" />
            <CorroborationBadge level={c.corroboration_level} />
          </div>
          <SafeText text={c.evidence_text} as="p" className="text-gray-600 text-xs line-clamp-2" />
          <button
            onClick={() => { if (confirm("Request deletion?")) deleteMutation.mutate(c.id); }}
            className="text-xs text-red-500 hover:text-red-700"
          >
            Request deletion
          </button>
        </div>
      ))}
    </div>
  );
}
