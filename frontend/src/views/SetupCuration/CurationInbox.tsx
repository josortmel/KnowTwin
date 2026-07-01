import { useState } from "react";
import { useClaims, usePromoteClaim } from "../../hooks/useClaims";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { StateBadge } from "../../components/StateBadge";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";

interface Props { projectId: number }

export function CurationInbox({ projectId }: Props) {
  const { data: claims, isLoading, error } = useClaims(projectId);
  const promote = usePromoteClaim();
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const filtered = claims?.filter(c => {
    if (filter === "pending") return c.corroboration_level === "single_source";
    if (filter === "draft") return c.corroboration_level === "draft";
    return true;
  }) ?? [];

  const handleApprove = () => {
    if (!confirmId) return;
    promote.mutate({ claimId: confirmId, newLevel: "validated" });
    setConfirmId(null);
  };

  return (
    <div className="border rounded p-4">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-semibold">Curation Inbox</h3>
        <select value={filter} onChange={e => setFilter(e.target.value)}
          className="border rounded px-2 py-1 text-sm">
          <option value="all">All</option>
          <option value="pending">Pending review</option>
          <option value="draft">Draft</option>
        </select>
      </div>
      {isLoading && <Loading />}
      {error && <p className="text-red-500 text-sm">{String(error)}</p>}
      {filtered.length === 0 && !isLoading && <EmptyState message="No claims to review" />}
      <div className="space-y-2">
        {filtered.map(c => (
          <div key={c.id} className="border rounded p-3 text-sm">
            <div className="flex justify-between items-start">
              <div>
                <span className="font-medium"><SafeText text={c.subject_entity} /></span>
                <span className="text-gray-400 mx-1">.</span>
                <SafeText text={c.predicate} />
              </div>
              <div className="flex gap-1">
                <CorroborationBadge level={c.corroboration_level} />
                {c.dispute_state !== "undisputed" && <StateBadge state={c.dispute_state} />}
              </div>
            </div>
            <p className="text-gray-600 mt-1 text-xs"><SafeText text={c.evidence_text} /></p>
            {c.corroboration_level !== "validated" && c.corroboration_level !== "rejected" && (
              <button onClick={() => setConfirmId(c.id)}
                className="mt-2 px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700">
                Approve
              </button>
            )}
          </div>
        ))}
      </div>
      <ConfirmDialog
        open={!!confirmId}
        title="Approve Claim"
        message="Promote this claim to 'validated'? This is a privileged override."
        confirmLabel="Approve"
        onConfirm={handleApprove}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  );
}
