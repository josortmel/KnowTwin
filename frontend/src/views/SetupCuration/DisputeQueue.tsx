import { useState } from "react";
import { useClaims, useUpdateClaim } from "../../hooks/useClaims";
import { SafeText } from "../../components/SafeText";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";

interface Props { projectId: number }

export function DisputeQueue({ projectId }: Props) {
  const { data: claims, isLoading, error } = useClaims(projectId);
  const update = useUpdateClaim();
  const [resolveId, setResolveId] = useState<string | null>(null);

  const disputed = claims
    ?.filter(c => c.dispute_state === "disputed")
    .sort((a, b) => (b.criticality ?? 0) - (a.criticality ?? 0)) ?? [];

  const handleResolve = () => {
    if (!resolveId) return;
    update.mutate({
      claimId: resolveId,
      body: { dispute_state: "resolved_in_favor" },
    });
    setResolveId(null);
  };

  return (
    <div className="border rounded p-4">
      <h3 className="font-semibold mb-3">Dispute Queue</h3>
      {isLoading && <Loading />}
      {error && <p className="text-red-500 text-sm">{String(error)}</p>}
      {disputed.length === 0 && !isLoading && <EmptyState message="No disputed claims" />}
      <div className="space-y-2">
        {disputed.map(c => (
          <div key={c.id} className="border border-red-200 rounded p-3 text-sm bg-red-50">
            <div className="flex justify-between">
              <span className="font-medium"><SafeText text={c.subject_entity} /></span>
              <span className="text-xs text-gray-400">criticality {c.criticality}</span>
            </div>
            <p className="text-gray-600 text-xs mt-1"><SafeText text={c.evidence_text} /></p>
            <button onClick={() => setResolveId(c.id)}
              className="mt-2 px-2 py-1 text-xs bg-amber-600 text-white rounded hover:bg-amber-700">
              Resolve
            </button>
          </div>
        ))}
      </div>
      <ConfirmDialog
        open={!!resolveId}
        title="Resolve Dispute"
        message="Resolve this dispute in favor of the claim? Coverage will be updated."
        confirmLabel="Resolve"
        onConfirm={handleResolve}
        onCancel={() => setResolveId(null)}
      />
    </div>
  );
}
