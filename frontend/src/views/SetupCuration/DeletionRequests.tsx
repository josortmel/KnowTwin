import { useState } from "react";
import { useDeletionRequests, useReviewDeletion, type ReviewDecision } from "../../hooks/useDeletions";
import { pushToast } from "../../lib/toast";
import { Panel, PanelState } from "../../components/Panel";
import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { StateBadge } from "../../components/StateBadge";
import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";

interface Props {
  projectId: number;
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function DeletionRequests({ projectId }: Props) {
  const { data, isLoading, error } = useDeletionRequests(projectId);
  const review = useReviewDeletion();
  const [action, setAction] = useState<{ id: string; decision: ReviewDecision } | null>(null);

  const pending = (data ?? []).filter((r) => r.status === "pending");

  const submit = (note?: string) => {
    if (!action) return;
    const { id, decision } = action;
    setAction(null);
    review.mutate(
      { requestId: id, decision, note },
      {
        onSuccess: () =>
          pushToast(decision === "approve" ? "Claim permanently deleted" : "Deletion request rejected", {
            tone: decision === "approve" ? "success" : "info",
          }),
        onError: (e) => pushToast(`Review failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  return (
    <Panel title="Deletion Requests" tag={`${pending.length} pending`}>
      <PanelState
        loading={isLoading}
        error={!!error}
        empty={!isLoading && !error && pending.length === 0}
        emptyLabel="No pending deletion requests"
      >
        <div className="flex flex-col gap-2">
          {pending.map((r) => (
            <GlassCard key={r.id} className="p-card-lg">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] text-ink-2">claim {r.claim_id.slice(0, 8)}…</span>
                <StateBadge state={r.status} />
              </div>
              {r.reason && <SafeText text={r.reason} as="p" className="mt-1.5 font-body text-[13px] leading-relaxed text-ink-1" />}
              <div className="mt-1 font-mono text-[10px] text-ink-3">
                requested by {r.requested_by ?? "—"} · {new Date(r.created_at).toLocaleDateString()}
              </div>
              <div className="mt-2 flex gap-2">
                <Button variant="danger" onClick={() => setAction({ id: r.id, decision: "approve" })} className="px-3 py-1.5 text-[12px]">
                  Approve (delete)
                </Button>
                <Button variant="default" onClick={() => setAction({ id: r.id, decision: "reject" })} className="px-3 py-1.5 text-[12px]">
                  Reject
                </Button>
              </div>
            </GlassCard>
          ))}
        </div>
      </PanelState>

      <ConfirmDialog
        open={!!action}
        title={action?.decision === "approve" ? "Approve deletion" : "Reject deletion"}
        message={
          action?.decision === "approve"
            ? "This permanently deletes the claim and cannot be undone."
            : "Reject this deletion request. The claim is kept."
        }
        confirmLabel={action?.decision === "approve" ? "Delete permanently" : "Reject"}
        destructive={action?.decision === "approve"}
        notePrompt="Note (optional)"
        onConfirm={submit}
        onCancel={() => setAction(null)}
      />
    </Panel>
  );
}
