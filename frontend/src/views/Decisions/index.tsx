import { useState, type ReactNode } from "react";
import { GlassCard } from "../../components/GlassCard";
import { PanelState } from "../../components/Panel";
import { Button } from "../../components/Button";
import { SafeText } from "../../components/SafeText";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DisputeBadge } from "../../components/DisputeBadge";
import { pushToast } from "../../lib/toast";
import { useAttentionSummary } from "../../hooks/useDashboard";
import { useInboxDetails, useUpdateStaleness, type InboxItem, type Staleness } from "../../hooks/useDecisions";
import { useResolveDispute, useAssignResolver, type Resolution } from "../../hooks/useDisputes";
import { useReviewDeletion } from "../../hooks/useDeletions";
import { useReviewAlias } from "../../hooks/useOntology";
import { useResolvedClaims, useReverseDispute, type Claim } from "../../hooks/useClaims";

const LIMIT = 20;
const ACCENT = "var(--sec-decisions)";

// Urgency order (Lienzo): disputes → deletions (GDPR) → the rest.
const CLASSES: { key: string; label: string }[] = [
  { key: "pending_disputes", label: "Contradictions" },
  { key: "pending_deletions", label: "Deletions" },
  { key: "low_trust_documents", label: "Low trust" },
  { key: "stale_claims", label: "Stale knowledge" },
  { key: "pending_alias_candidates", label: "Duplicates" },
  { key: "unconfirmed_relations", label: "Relations" },
];

const WHY: Record<string, string> = {
  pending_disputes: "This claim has conflicting evidence from different sources — pick the version the twin should trust.",
  pending_deletions: "An employee requested deletion of this claim (GDPR). Approving erases it permanently.",
  low_trust_documents: "This document's trust tier is low. Review its source before its claims are relied on.",
  stale_claims: "This claim's evidence is past its freshness window. Decide whether it still holds.",
  pending_alias_candidates: "Two entity names look like the same thing. Approving merges them in the graph.",
  unconfirmed_relations: "This relation was inferred but not yet confirmed by a documentary or human source.",
};

const day = (iso?: string): string => (iso ? iso.slice(0, 10) : "—");
const pct = (c?: number): string => `${Math.round((c ?? 0) * 100)}%`;

function ClassTab({ active, label, count, onClick }: { active: boolean; label: string; count: number; onClick: () => void }) {
  // §1.3: active state via tint+border, never colored text.
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11.5px] transition-colors ${active ? "text-ink-1" : "text-ink-3 hover:text-ink-1"}`}
      style={active ? { background: "color-mix(in srgb, var(--sec-decisions) 13%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-decisions) 38%, transparent)" } : { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
    >
      <span>{label}</span>
      <span
        className="min-w-[20px] rounded-[20px] px-1.5 py-0.5 text-center text-[10px] tabular-nums text-ink-1"
        style={count > 0 ? { background: "color-mix(in srgb, var(--sec-decisions) 22%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-decisions) 45%, transparent)" } : { background: "var(--card-bg)", color: "var(--ink-3)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
      >
        {count}
      </span>
    </button>
  );
}

function Row({ active, onClick, lead, meta }: { active: boolean; onClick: () => void; lead: ReactNode; meta: ReactNode }) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      className="grid w-full grid-cols-[16px_1fr] items-start gap-3 border-b border-[var(--card-hairline)] px-3 py-3 text-left transition-colors last:border-0 hover:bg-[var(--inset)]"
      style={active ? { background: "color-mix(in srgb, var(--sec-decisions) 9%, transparent)" } : undefined}
    >
      <span className="mt-1 grid h-[14px] w-[14px] place-items-center rounded-full" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
        <span className="h-[6px] w-[6px] rounded-full" style={{ background: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
      </span>
      <span className="min-w-0">
        <span className="line-clamp-2 block text-[12.5px] leading-snug text-ink-1">{lead}</span>
        <span className="mt-1.5 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-ink-3">{meta}</span>
      </span>
    </button>
  );
}

function MetaCell({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-md p-2.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="truncate font-mono text-[12.5px] text-ink-1">
        <SafeText text={v} />
      </div>
      <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">{k}</div>
    </div>
  );
}

function DetailHead({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2">
      <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: ACCENT, boxShadow: `0 0 8px ${ACCENT}` }} />
      {label}
      {children}
    </div>
  );
}

function WhyBox({ text }: { text: string }) {
  return (
    <div className="mt-4 flex items-start gap-2.5 rounded-md px-3.5 py-3" style={{ background: "color-mix(in srgb, var(--sec-decisions) 8%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-decisions) 25%, transparent)" }}>
      <span className="mt-[3px] h-[7px] w-[7px] flex-none rounded-full" style={{ background: ACCENT }} />
      <div>
        <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-2">Why this is here</div>
        <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2">{text}</div>
      </div>
    </div>
  );
}

function NoteInput({ value, onChange, placeholder = "Resolution note (optional)…", invalid = false }: { value: string; onChange: (v: string) => void; placeholder?: string; invalid?: boolean }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={2}
      aria-invalid={invalid}
      className="w-full resize-none rounded-md px-2.5 py-2 font-mono text-[11.5px] text-ink-1 outline-none"
      style={{ background: "var(--field-bg)", boxShadow: invalid ? "inset 0 0 0 1px var(--red)" : "inset 0 0 0 1px var(--card-hairline)" }}
    />
  );
}

// ── Dispute (KnowTwin NEW) ────────────────────────────────────────────────────
function DisputeDetail({ item, acting, onResolve, onAssign }: { item: InboxItem; acting: boolean; onResolve: (id: string, r: Resolution, note: string) => void; onAssign: (id: string, uid: number) => void }) {
  const [note, setNote] = useState("");
  const [resolver, setResolver] = useState("");
  // Backend requires resolution_note (min 1 char) → gate the resolve actions on it.
  const noteEmpty = note.trim().length === 0;
  return (
    <div className="flex h-full flex-col">
      <DetailHead label={`Disputed · ${item.dispute_state ?? ""}`} />
      <p className="mt-3 text-[13.5px] leading-relaxed text-ink-1">
        <SafeText text={item.evidence_text ?? item.content ?? ""} />
      </p>
      <WhyBox text={WHY.pending_disputes} />
      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <MetaCell k="Source" v={item.source_type ?? "—"} />
        <MetaCell k="Reported" v={item.agent_identifier ?? "—"} />
        <MetaCell k="Created" v={day(item.created_at)} />
        <MetaCell k="Updated" v={day(item.updated_at)} />
      </div>
      <div className="flex-1" />
      <div className="mt-4 flex flex-col gap-2.5">
        <NoteInput value={note} onChange={setNote} placeholder="Resolution note (required) — explain your call…" invalid={noteEmpty} />
        {noteEmpty && <div className="font-mono text-[10px] text-ink-3">A resolution note is required before you can resolve this dispute.</div>}
        <div className="flex gap-2.5">
          <Button variant="primary" disabled={acting || noteEmpty} onClick={() => onResolve(item.id, "in_favor", note.trim())} className="flex-1 py-2.5 text-[12.5px]">
            Resolve in favor
          </Button>
          <Button variant="default" disabled={acting || noteEmpty} onClick={() => onResolve(item.id, "against", note.trim())} className="flex-1 py-2.5 text-[12.5px]">
            Resolve against
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={resolver}
            onChange={(e) => setResolver(e.target.value.replace(/\D/g, ""))}
            placeholder="Resolver user id"
            inputMode="numeric"
            className="min-w-0 flex-1 rounded-md px-2.5 py-2 font-mono text-[11.5px] text-ink-1 outline-none"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          />
          <Button variant="default" disabled={acting || !resolver} onClick={() => onAssign(item.id, Number(resolver))} className="px-3 py-2 text-[12px]">
            Assign
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Deletion (KnowTwin NEW — GDPR) ────────────────────────────────────────────
function DeletionDetail({ item, acting, onReview }: { item: InboxItem; acting: boolean; onReview: (id: string, decision: "approve" | "reject", note: string) => void }) {
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="flex h-full flex-col">
      <DetailHead label="Deletion request" />
      <p className="mt-3 text-[13.5px] leading-relaxed text-ink-1">
        <SafeText text={item.evidence_text ?? item.content ?? ""} />
      </p>
      <WhyBox text={WHY.pending_deletions} />
      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <MetaCell k="Reason" v={item.reason ?? "—"} />
        <MetaCell k="Status" v={item.status ?? "—"} />
        <MetaCell k="Created" v={day(item.created_at)} />
        <MetaCell k="Source" v={item.source_type ?? "—"} />
      </div>
      <div className="flex-1" />
      <div className="mt-4 flex flex-col gap-2.5">
        <NoteInput value={note} onChange={setNote} />
        {confirm ? (
          <div className="flex flex-col gap-2.5">
            <div className="text-[11.5px] leading-snug text-ink-1">This permanently deletes the claim and cannot be undone.</div>
            <div className="flex gap-2.5">
              <Button variant="danger" disabled={acting} onClick={() => onReview(item.id, "approve", note)} className="flex-1 py-2.5 text-[12.5px]">
                Approve deletion
              </Button>
              <Button variant="default" disabled={acting} onClick={() => setConfirm(false)} className="px-4 py-2.5 text-[12.5px]">
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2.5">
            <Button variant="danger" disabled={acting} onClick={() => setConfirm(true)} className="flex-1 py-2.5 text-[12.5px]">
              Approve
            </Button>
            <Button variant="default" disabled={acting} onClick={() => onReview(item.id, "reject", note)} className="flex-1 py-2.5 text-[12.5px]">
              Reject
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Stale ─────────────────────────────────────────────────────────────────────
function StaleDetail({ item, acting, onStale }: { item: InboxItem; acting: boolean; onStale: (id: string, s: Staleness) => void }) {
  return (
    <div className="flex h-full flex-col">
      <DetailHead label={`Stale claim · ${item.type ?? ""}`} />
      <p className="mt-3 text-[13.5px] leading-relaxed text-ink-1">
        <SafeText text={item.content ?? item.evidence_text ?? ""} />
      </p>
      <WhyBox text={WHY.stale_claims} />
      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <MetaCell k="Author" v={item.agent_identifier ?? "—"} />
        <MetaCell k="Type" v={item.type ?? "—"} />
        <MetaCell k="Staleness" v={item.staleness ?? "—"} />
        <MetaCell k="Created" v={day(item.created_at)} />
      </div>
      <div className="flex-1" />
      <div className="mt-5 flex gap-2.5">
        <Button variant="primary" disabled={acting} onClick={() => onStale(item.id, "active")} className="flex-1 py-2.5 text-[12.5px]">
          Resolve
        </Button>
        <Button variant="default" disabled={acting} onClick={() => onStale(item.id, "dormant")} className="flex-1 py-2.5 text-[12.5px]">
          Defer
        </Button>
        <Button variant="danger" disabled={acting} onClick={() => onStale(item.id, "archived")} className="flex-1 py-2.5 text-[12.5px]">
          Dismiss
        </Button>
      </div>
    </div>
  );
}

// ── Alias ─────────────────────────────────────────────────────────────────────
function AliasDetail({ item, acting, onReview }: { item: InboxItem; acting: boolean; onReview: (id: string, status: "approved" | "rejected") => void }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="flex h-full flex-col">
      <DetailHead label="Alias candidate" />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[15px] leading-tight text-ink-1">
        <span className="font-semibold">
          <SafeText text={item.source_name ?? ""} />
        </span>
        <span className="text-ink-3">→</span>
        <span className="font-semibold">
          <SafeText text={item.target_node_name ?? ""} />
        </span>
      </div>
      <WhyBox text={WHY.pending_alias_candidates} />
      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <MetaCell k="Confidence" v={pct(item.confidence)} />
        <MetaCell k="Occurrences" v={String(item.occurrences ?? "—")} />
      </div>
      <div className="flex-1" />
      {confirm ? (
        <div className="mt-5 flex flex-col gap-2.5">
          <div className="text-[11.5px] leading-snug text-ink-1">
            Merge <SafeText text={item.source_name ?? ""} /> into <SafeText text={item.target_node_name ?? ""} /> in the graph? This cannot be undone from here.
          </div>
          <div className="flex gap-2.5">
            <Button variant="primary" disabled={acting} onClick={() => onReview(item.id, "approved")} className="flex-1 py-2.5 text-[12.5px]">
              Confirm merge
            </Button>
            <Button variant="default" disabled={acting} onClick={() => setConfirm(false)} className="px-4 py-2.5 text-[12.5px]">
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-5 flex gap-2.5">
          <Button variant="primary" disabled={acting} onClick={() => setConfirm(true)} className="flex-1 py-2.5 text-[12.5px]">
            Approve
          </Button>
          <Button variant="danger" disabled={acting} onClick={() => onReview(item.id, "rejected")} className="flex-1 py-2.5 text-[12.5px]">
            Reject
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Disabled (no action endpoint) ─────────────────────────────────────────────
function DisabledDetail({ item, decisionClass, label }: { item: InboxItem; decisionClass: string; label: string }) {
  return (
    <div className="flex h-full flex-col">
      <DetailHead label={label} />
      <p className="mt-3 text-[13.5px] leading-relaxed text-ink-1">
        <SafeText text={item.content ?? item.evidence_text ?? item.source_name ?? ""} />
      </p>
      <WhyBox text={WHY[decisionClass] ?? ""} />
      <div className="flex-1" />
      <div className="mt-5 flex gap-2.5">
        <Button variant="default" disabled className="flex-1 py-2.5 text-[12.5px]">
          Requires backend action
        </Button>
      </div>
    </div>
  );
}

// ── History (resolved disputes) ───────────────────────────────────────────────
// NOTE: /claims (api/claims.py ClaimResponse) does NOT return resolution_note,
// resolved_by or resolved_at — only dispute_state + updated_at. We show what the
// contract exposes; updated_at is used as the resolution timestamp.
function HistoryPanel() {
  const resolved = useResolvedClaims(1);
  const reverse = useReverseDispute();
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const items = resolved.data ?? [];

  const onReverse = (id: string) =>
    reverse.mutate(id, {
      onSuccess: () => pushToast("Dispute reopened", { tone: "success" }),
      onError: (e) => pushToast(e instanceof Error ? e.message : "Reverse failed", { tone: "error" }),
    });

  return (
    <GlassCard className="flex max-h-[calc(100vh-220px)] flex-col p-2">
      <PanelState loading={resolved.isPending} error={resolved.isError} onRetry={() => void resolved.refetch()} empty={!resolved.isPending && items.length === 0} emptyLabel="No resolved disputes yet">
        <div className="min-h-0 flex-1 overflow-y-auto">
          {items.map((c: Claim) => {
            const object = c.object_entity ?? c.object_value ?? "";
            return (
              <div key={c.id} className="grid grid-cols-[1fr_auto] items-start gap-3 border-b border-[var(--card-hairline)] px-3 py-3 last:border-0">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    <SafeText text={c.subject_entity} className="font-mono text-[12px] text-ink-1" />
                    <span className="font-mono text-[11px] text-ink-3">·</span>
                    <SafeText text={c.predicate} className="font-mono text-[12px] text-ink-2" />
                    {object && (<><span className="font-mono text-[11px] text-ink-3">·</span><SafeText text={object} className="font-mono text-[12px] text-ink-2" /></>)}
                  </div>
                  <SafeText text={c.evidence_text} as="p" className="mt-1.5 line-clamp-2 font-body text-[12.5px] leading-relaxed text-ink-1" />
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[10px] text-ink-3">
                    <DisputeBadge state={c.dispute_state} />
                    <span>·</span>
                    <span>resolved {(c.updated_at ?? c.created_at).slice(0, 10)}</span>
                  </div>
                </div>
                <Button variant="default" disabled={reverse.isPending} onClick={() => setConfirmId(c.id)} className="flex-none px-3 py-1.5 text-[11.5px]">
                  Reverse
                </Button>
              </div>
            );
          })}
        </div>
      </PanelState>

      <ConfirmDialog
        open={!!confirmId}
        title="Reopen this dispute?"
        message="This moves the claim back to 'disputed' and returns it to the dispute queue for a fresh decision."
        confirmLabel="Reopen"
        onConfirm={() => { if (confirmId) onReverse(confirmId); setConfirmId(null); }}
        onCancel={() => setConfirmId(null)}
      />
    </GlassCard>
  );
}

// ── Decisions Inbox ───────────────────────────────────────────────────────────
export function DecisionsView() {
  const summary = useAttentionSummary();
  const resolve = useResolveDispute();
  const assign = useAssignResolver();
  const review = useReviewDeletion();
  const staleness = useUpdateStaleness();
  const alias = useReviewAlias();
  const history = useResolvedClaims(1); // for the History tab count (shared cache)

  const [decisionClass, setDecisionClass] = useState("pending_disputes");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const details = useInboxDetails(decisionClass, LIMIT, offset, decisionClass !== "history");
  const items = details.data?.items ?? [];
  const total = details.data?.total ?? 0;
  const selected = items.find((i) => i.id === selectedId) ?? items[0] ?? null;
  const acting = resolve.isPending || assign.isPending || review.isPending || staleness.isPending || alias.isPending;

  const onDone = (msg: string) => {
    pushToast(msg, { tone: "success" });
    setSelectedId(null);
    details.refetch();
    summary.refetch();
  };
  const onErr = (e: unknown) => pushToast(e instanceof Error ? e.message : "Action failed", { tone: "error" });

  const onResolve = (id: string, resolution: Resolution, note: string) =>
    resolve.mutate({ claimId: id, resolution, note }, { onSuccess: () => onDone("Dispute resolved"), onError: onErr });
  const onAssign = (id: string, uid: number) =>
    assign.mutate({ claimId: id, resolverUserId: uid }, { onSuccess: () => onDone("Resolver assigned"), onError: onErr });
  const onReviewDeletion = (id: string, decision: "approve" | "reject", note: string) =>
    review.mutate({ requestId: id, decision, note: note || undefined }, { onSuccess: () => onDone(decision === "approve" ? "Claim deleted" : "Deletion rejected"), onError: onErr });
  const onStale = (id: string, s: Staleness) =>
    staleness.mutate({ id, staleness: s }, { onSuccess: () => onDone("Claim updated"), onError: onErr });
  const onAlias = (id: string, status: "approved" | "rejected") =>
    alias.mutate({ id: Number(id), status, ...(status === "approved" ? { merge: true } : {}) }, { onSuccess: () => onDone(status === "approved" ? "Entities merged" : "Alias rejected"), onError: onErr });

  const pick = (c: string) => {
    setDecisionClass(c);
    setOffset(0);
    setSelectedId(null);
  };

  const is403 = /403/.test(details.error instanceof Error ? details.error.message : "");
  const activeLabel = CLASSES.find((c) => c.key === decisionClass)?.label ?? "";
  const rowLead = (it: InboxItem) => it.source_name ? <span><SafeText text={it.source_name} /> <span className="text-ink-3">→</span> <SafeText text={it.target_node_name ?? ""} /></span> : <SafeText text={it.evidence_text ?? it.content ?? ""} />;

  return (
    <>
      <div className="mb-[18px] mt-1.5 px-0.5">
        <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Decisions</h1>
        <p className="mt-1.5 text-[12.5px] text-ink-3">Everything that needs a call — contradictions, deletions, duplicates, and stale knowledge.</p>
      </div>

      <div role="tablist" className="mb-4 flex flex-wrap gap-2">
        {CLASSES.map((c) => (
          <ClassTab key={c.key} active={decisionClass === c.key} label={c.label} count={summary.data?.classes?.[c.key] ?? 0} onClick={() => pick(c.key)} />
        ))}
        <ClassTab active={decisionClass === "history"} label="History" count={history.data?.length ?? 0} onClick={() => pick("history")} />
      </div>

      {decisionClass === "history" ? (
        <HistoryPanel />
      ) : is403 ? (
        <GlassCard className="p-[18px]">
          <div className="grid place-items-center py-16 font-mono text-[12.5px] text-ink-3">This inbox is limited to curators and admins.</div>
        </GlassCard>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <GlassCard className="flex max-h-[calc(100vh-220px)] flex-col p-2">
            <PanelState loading={details.isPending} error={details.isError} onRetry={() => void details.refetch()} empty={!details.isPending && items.length === 0} emptyLabel="All clear — nothing to review here">
              <div role="listbox" className="min-h-0 flex-1 overflow-y-auto">
                {items.map((it) => (
                  <Row
                    key={it.id}
                    active={selected?.id === it.id}
                    onClick={() => setSelectedId(it.id)}
                    lead={rowLead(it)}
                    meta={
                      <>
                        <span>{day(it.created_at)}</span>
                        {it.confidence != null && (
                          <>
                            <span>·</span>
                            <span>{pct(it.confidence)}</span>
                          </>
                        )}
                        {it.source_type && (
                          <>
                            <span>·</span>
                            <span>{it.source_type}</span>
                          </>
                        )}
                      </>
                    }
                  />
                ))}
              </div>
              <div className="mt-1 flex flex-none items-center justify-between gap-2 border-t border-[var(--card-hairline)] px-2 py-2">
                <span className="font-mono text-[10px] tabular-nums text-ink-3">
                  {total === 0 ? 0 : offset + 1}–{Math.min(offset + LIMIT, total)} of {total}
                </span>
                <div className="flex gap-1.5">
                  <button type="button" onClick={() => setOffset((o) => Math.max(0, o - LIMIT))} disabled={offset === 0} className="rounded-sm px-2.5 py-1 font-mono text-[11px] text-ink-2 transition-colors disabled:opacity-40" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                    Prev
                  </button>
                  <button type="button" onClick={() => setOffset((o) => o + LIMIT)} disabled={offset + LIMIT >= total} className="rounded-sm px-2.5 py-1 font-mono text-[11px] text-ink-2 transition-colors disabled:opacity-40" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                    Next
                  </button>
                </div>
              </div>
            </PanelState>
          </GlassCard>

          <GlassCard className="flex max-h-[calc(100vh-220px)] flex-col p-[18px]">
            {selected ? (
              decisionClass === "pending_disputes" ? (
                <DisputeDetail key={selected.id} item={selected} acting={acting} onResolve={onResolve} onAssign={onAssign} />
              ) : decisionClass === "pending_deletions" ? (
                <DeletionDetail key={selected.id} item={selected} acting={acting} onReview={onReviewDeletion} />
              ) : decisionClass === "stale_claims" ? (
                <StaleDetail key={selected.id} item={selected} acting={acting} onStale={onStale} />
              ) : decisionClass === "pending_alias_candidates" ? (
                <AliasDetail key={selected.id} item={selected} acting={acting} onReview={onAlias} />
              ) : (
                <DisabledDetail key={selected.id} item={selected} decisionClass={decisionClass} label={activeLabel} />
              )
            ) : (
              <div className="grid h-full place-items-center px-6 text-center font-mono text-[12px] text-ink-3">{details.isPending ? "" : "Select an item to review it."}</div>
            )}
          </GlassCard>
        </div>
      )}
    </>
  );
}
