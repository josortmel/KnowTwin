import { useState } from "react";
import { useDisputes, useResolveDispute, useAssignResolver, type Dispute, type Resolution } from "../../hooks/useDisputes";
import { useProjectMembers } from "../../hooks/useProjectMembers";
import { pushToast } from "../../lib/toast";
import { Panel, PanelState } from "../../components/Panel";
import { DisputePair } from "./DisputePair";
import { ResolveDialog } from "./ResolveDialog";

interface Props {
  projectId: number;
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function DisputeQueue({ projectId }: Props) {
  const { data: disputes, isLoading, error } = useDisputes(projectId);
  const resolve = useResolveDispute();
  const assign = useAssignResolver();
  const { data: members } = useProjectMembers(projectId);
  const [active, setActive] = useState<Dispute | null>(null);

  // Highest criticality first — the disputes that most block coverage.
  const sorted = (disputes ?? []).slice().sort((a, b) => b.claim.criticality - a.claim.criticality);

  const handleResolve = (resolution: Resolution, note: string) => {
    if (!active) return;
    const claimId = active.claim.claim_id;
    setActive(null);
    resolve.mutate(
      { claimId, resolution, note },
      {
        onSuccess: () => pushToast("Dispute resolved", { tone: "success" }),
        onError: (e) => pushToast(`Resolve failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  const handleAssign = (claimId: string, resolverUserId: number) => {
    assign.mutate(
      { claimId, resolverUserId },
      {
        onSuccess: () => pushToast("Resolver assigned", { tone: "success" }),
        onError: (e) => pushToast(`Assign failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  return (
    <Panel title="Dispute Queue" tag={`${sorted.length} open`}>
      <PanelState
        loading={isLoading}
        error={!!error}
        empty={!isLoading && !error && sorted.length === 0}
        emptyLabel="No open disputes"
      >
        <div className="flex flex-col gap-5">
          {sorted.map((d) => (
            <DisputePair key={d.claim.claim_id} dispute={d} onResolve={setActive} onAssign={handleAssign} assigning={assign.isPending} members={members} />
          ))}
        </div>
      </PanelState>

      <ResolveDialog dispute={active} onConfirm={handleResolve} onCancel={() => setActive(null)} submitting={resolve.isPending} />
    </Panel>
  );
}
