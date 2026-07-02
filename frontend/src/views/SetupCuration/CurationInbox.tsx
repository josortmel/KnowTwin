import { useState } from "react";
import { useClaims, usePromoteClaim } from "../../hooks/useClaims";
import { useBatch, type BatchAction } from "../../hooks/useBatch";
import { pushToast } from "../../lib/toast";
import { ClaimRow } from "./ClaimRow";
import { SegmentedControl } from "../../components/SegmentedControl";
import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { AuditDrawer } from "../../components/AuditDrawer";
import { Panel, PanelState } from "../../components/Panel";

interface Props {
  projectId: number;
}

const FILTERS = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "draft", label: "Draft" },
  { value: "disputed", label: "Disputed" },
];

const SENSITIVITIES = [
  { value: "public", label: "Public" },
  { value: "team", label: "Team" },
  { value: "restricted", label: "Restricted" },
];

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function CurationInbox({ projectId }: Props) {
  const { data: claims, isLoading, error } = useClaims(projectId);
  const batch = useBatch();
  const promote = usePromoteClaim();
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [auditId, setAuditId] = useState<string | null>(null);

  const filtered = (claims ?? []).filter((c) => {
    if (filter === "pending") return c.corroboration_level === "single_source";
    if (filter === "draft") return c.corroboration_level === "draft";
    if (filter === "disputed") return c.dispute_state === "disputed";
    return true;
  });

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allSelected = filtered.length > 0 && filtered.every((c) => selected.has(c.id));
  const toggleAll = () =>
    setSelected((prev) => {
      if (allSelected) return new Set();
      const next = new Set(prev);
      filtered.forEach((c) => next.add(c.id));
      return next;
    });

  const clearSel = () => setSelected(new Set());

  const runBatch = (action: BatchAction, value?: string) => {
    const ids = [...selected];
    if (ids.length === 0) return;
    batch.mutate(
      { ids, action, value },
      {
        onSuccess: (res) => {
          const failed = res?.failed?.length ?? 0;
          const ok = res?.succeeded?.length ?? ids.length - failed;
          if (failed > 0) pushToast(`${ok} done · ${failed} failed`, { tone: "error" });
          else {
            const verb = action === "approve" ? "approved" : action === "reject" ? "rejected" : "updated";
            pushToast(`${ok} claim${ok === 1 ? "" : "s"} ${verb}`, { tone: "success" });
          }
          clearSel();
        },
        onError: (e) => pushToast(`Batch failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  const forceApprove = (id: string) => {
    promote.mutate(
      { claimId: id, newLevel: "validated", force: true },
      {
        onSuccess: () => pushToast("Claim approved", { tone: "success" }),
        // The server enforces the interview cap even with force → surface its error.
        onError: (e) => pushToast(`Could not approve: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  return (
    <Panel
      title="Curation Inbox"
      tag={`${filtered.length} / ${claims?.length ?? 0}`}
      control={<SegmentedControl options={FILTERS} value={filter} onChange={setFilter} ariaLabel="Filter claims" />}
    >
      <PanelState loading={isLoading} error={!!error} empty={!isLoading && !error && filtered.length === 0} emptyLabel="No claims to review">
        {filtered.length > 0 && (
          <label className="mb-2 flex items-center gap-2 px-1 font-mono text-[11px] text-ink-3">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} className="h-3.5 w-3.5 accent-accent" aria-label="Select all" />
            Select all
          </label>
        )}
        <div className="flex flex-col gap-2 pb-16">
          {filtered.map((c) => (
            <ClaimRow
              key={c.id}
              claim={c}
              selected={selected.has(c.id)}
              onToggle={() => toggle(c.id)}
              onApprove={() => setConfirmId(c.id)}
              onAudit={() => setAuditId(c.id)}
              approving={promote.isPending && promote.variables?.claimId === c.id}
            />
          ))}
        </div>
      </PanelState>

      {selected.size > 0 && (
        <div
          className="fixed bottom-6 left-1/2 z-[60] flex -translate-x-1/2 items-center gap-3 rounded-btn px-4 py-2.5"
          style={{ background: "var(--card-bg)", boxShadow: "var(--elev)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)" }}
        >
          <span className="font-mono text-[12px] text-ink-1">{selected.size} selected</span>
          <Button variant="primary" onClick={() => runBatch("approve")} loading={batch.isPending} className="px-3 py-1.5 text-[12px]">
            Approve
          </Button>
          <Button variant="danger" onClick={() => runBatch("reject")} loading={batch.isPending} className="px-3 py-1.5 text-[12px]">
            Reject
          </Button>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Sensitivity</span>
            <SegmentedControl options={SENSITIVITIES} value="" onChange={(v) => runBatch("set_sensitivity", v)} ariaLabel="Set sensitivity" />
          </div>
          <button type="button" onClick={clearSel} aria-label="Clear selection" className="text-ink-3 transition-colors hover:text-ink-1">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} width={15} height={15}>
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}

      <AuditDrawer open={!!auditId} claimId={auditId} onClose={() => setAuditId(null)} />

      <ConfirmDialog
        open={!!confirmId}
        title="Force approve this claim?"
        message="Promotes the claim to 'validated', a privileged override. The server still enforces the interview cap and may reject it."
        confirmLabel="Approve"
        onConfirm={() => {
          if (confirmId) forceApprove(confirmId);
          setConfirmId(null);
        }}
        onCancel={() => setConfirmId(null)}
      />
    </Panel>
  );
}
