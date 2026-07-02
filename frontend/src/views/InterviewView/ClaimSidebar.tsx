import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../lib/api";
import { useRequestDeletion } from "../../hooks/useDeletions";
import { pushToast } from "../../lib/toast";
import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { ConfirmDialog } from "../../components/ConfirmDialog";
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

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function ClaimSidebar({ sessionId, claimIds }: ClaimSidebarProps) {
  const { data: claims, isLoading } = useQuery<Claim[]>({
    queryKey: ["session-claims", sessionId, claimIds.length],
    queryFn: async () => {
      if (!claimIds.length) return [];
      const results: Claim[] = [];
      for (const id of claimIds.slice(-20)) {
        try {
          results.push(await get<Claim>(`/claims/${id}`));
        } catch {
          /* claim may not be accessible */
        }
      }
      return results;
    },
    enabled: claimIds.length > 0,
  });

  const requestDeletion = useRequestDeletion();
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const submit = (reason?: string) => {
    if (!confirmId) return;
    const claimId = confirmId;
    setConfirmId(null);
    requestDeletion.mutate(
      { claimId, reason },
      {
        onSuccess: () => pushToast("Deletion requested — a curator will review it", { tone: "success" }),
        onError: (e) => pushToast(`Request failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  if (isLoading) return <Loading />;

  return (
    <div className="space-y-2">
      <h3 className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-3">Claims this session ({claimIds.length})</h3>
      {(!claims || claims.length === 0) && <p className="font-mono text-[12px] text-ink-3">No claims yet</p>}
      {claims?.map((c) => (
        <GlassCard key={c.id} className="p-3">
          <div className="flex items-center justify-between gap-2">
            <SafeText text={`${c.subject_entity} · ${c.predicate}`} className="font-mono text-[12px] text-ink-1" />
            <CorroborationBadge level={c.corroboration_level} />
          </div>
          <SafeText text={c.evidence_text} as="p" className="mt-1 line-clamp-2 font-body text-[12.5px] leading-relaxed text-ink-2" />
          <button
            type="button"
            onClick={() => setConfirmId(c.id)}
            className="mt-2 font-mono text-[11px] text-ink-2 underline underline-offset-2 transition-colors hover:text-ink-1"
          >
            Request deletion
          </button>
        </GlassCard>
      ))}

      <ConfirmDialog
        open={!!confirmId}
        title="Request deletion"
        message="Ask a curator to delete this claim (right to erasure). You can add a reason."
        confirmLabel="Request deletion"
        notePrompt="Reason (optional)"
        onConfirm={submit}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  );
}
