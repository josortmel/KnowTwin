import { useEffect, useMemo, useState } from "react";
import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { DisputeBadge } from "../../components/DisputeBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import { TrustTierBadge } from "../../components/TrustTierBadge";
import { useClaimsFiltered, type Claim } from "../../hooks/useClaims";
import { useTwinSearch, type TwinSource, type DisputeGroup } from "../../hooks/useTwin";
import { useDocuments, useDocumentDetail, useDocumentChunks, type Document } from "../../hooks/useDocuments";

const PROJECT_ID = 1;
const CORROBORATION = ["draft", "single_source", "corroborated", "corroborated_by_employee", "validated", "rejected"];
const DISPUTE = ["undisputed", "disputed", "resolved_in_favor", "resolved_against"];
const LIMITS = [20, 50, 100] as const;

const day = (iso?: string): string => (iso ? iso.slice(0, 10) : "");

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  // Active state carried by border+tint (not colored text — §1.3 WCAG).
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-[20px] px-2.5 py-1.5 font-mono text-[10.5px] transition-colors ${active ? "text-ink-1" : "text-ink-3 hover:text-ink-1"}`}
      style={{
        background: active ? "color-mix(in srgb, var(--accent) 13%, transparent)" : "var(--inset)",
        boxShadow: active ? "inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent)" : "inset 0 0 0 1px var(--card-hairline)",
      }}
    >
      {children}
    </button>
  );
}

// ── Claim / source rows ───────────────────────────────────────────────────────
function ClaimBadges({ corroboration, dispute, sensitivity, trustTier }: { corroboration: string; dispute: string; sensitivity: string; trustTier: number }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <CorroborationBadge level={corroboration} />
      {dispute !== "undisputed" && <DisputeBadge state={dispute} />}
      <SensitivityBadge level={sensitivity} />
      <TrustTierBadge tier={trustTier} />
    </div>
  );
}

function ClaimRow({ c }: { c: Claim }) {
  const object = c.object_value ?? c.object_entity ?? "";
  return (
    <div className="border-b border-[var(--card-hairline)] px-3 py-3 last:border-0">
      <div className="flex items-baseline gap-1.5 text-[13px] leading-snug text-ink-1">
        <span className="font-semibold">
          <SafeText text={c.subject_entity} />
        </span>
        <span className="font-mono text-[11px] text-ink-3">
          <SafeText text={c.predicate} />
        </span>
        {object && (
          <span>
            <SafeText text={object} />
          </span>
        )}
      </div>
      <div className="mt-1 line-clamp-2 font-mono text-[11.5px] leading-snug text-ink-2">
        <SafeText text={c.evidence_text} />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-ink-3">
        <span>{day(c.created_at)}</span>
        <span>·</span>
        <span className="rounded-sm px-1.5 py-0.5 text-ink-2" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
          <SafeText text={c.source_type} />
        </span>
      </div>
      <ClaimBadges corroboration={c.corroboration_level} dispute={c.dispute_state} sensitivity={c.sensitivity} trustTier={c.trust_tier} />
    </div>
  );
}

function SourceRow({ s }: { s: TwinSource }) {
  const object = s.object_value ?? s.object_entity ?? "";
  return (
    <div className="border-b border-[var(--card-hairline)] px-3 py-3 last:border-0">
      <div className="flex items-baseline gap-1.5 text-[13px] leading-snug text-ink-1">
        <span className="font-semibold">
          <SafeText text={s.subject_entity} />
        </span>
        <span className="font-mono text-[11px] text-ink-3">
          <SafeText text={s.predicate} />
        </span>
        {object && (
          <span>
            <SafeText text={object} />
          </span>
        )}
      </div>
      <div className="mt-1 line-clamp-2 font-mono text-[11.5px] leading-snug text-ink-2">
        <SafeText text={s.evidence_text} />
      </div>
      <ClaimBadges corroboration={s.corroboration_level} dispute={s.dispute_state} sensitivity={s.sensitivity} trustTier={0} />
    </div>
  );
}

// ── Twin answer (search mode) ─────────────────────────────────────────────────
function TwinAnswer({ answer, sources, disputes }: { answer: string; sources: TwinSource[]; disputes: DisputeGroup[] }) {
  return (
    <div className="mt-1">
      <div className="mb-3 rounded-md p-3.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
        <div className="mb-1 font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-3">Twin answer</div>
        <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-1">
          <SafeText text={answer} />
        </p>
      </div>

      {disputes.length > 0 && (
        <div className="mb-3">
          <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-3">
            <span className="h-[6px] w-[6px] rounded-full" style={{ background: "var(--accent)", boxShadow: "0 0 5px var(--accent)" }} />
            Disputed ({disputes.length})
          </div>
          <div className="flex flex-col gap-2">
            {disputes.map((d, i) => (
              <div key={`${d.subject_entity}-${d.predicate}-${i}`} className="rounded-md p-2.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                <div className="mb-1 font-mono text-[11px] text-ink-1">
                  <SafeText text={`${d.subject_entity} · ${d.predicate}`} />
                </div>
                {d.versions.map((v, j) => (
                  <div key={j} className="mt-1 border-l-2 pl-2 font-mono text-[11px] text-ink-2" style={{ borderColor: "var(--card-hairline)" }}>
                    <SafeText text={v.object_value ?? v.object_entity ?? v.evidence_text} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-1.5 font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-3">Sources ({sources.length})</div>
      {sources.length === 0 ? (
        <div className="grid place-items-center py-6 font-mono text-[12px] text-ink-3">No sources</div>
      ) : (
        sources.map((s) => <SourceRow key={s.claim_id} s={s} />)
      )}
    </div>
  );
}

// ── Documents tab ─────────────────────────────────────────────────────────────
function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} width={15} height={15}>
      <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

function DocRow({ d, onOpen }: { d: Document; onOpen: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(d.id)}
      className="grid w-full grid-cols-[16px_1fr_auto] items-center gap-3.5 border-b border-[var(--card-hairline)] px-3 py-3 text-left transition-colors last:border-0 hover:bg-[var(--inset)]"
    >
      <span className="flex-none text-ink-3">
        <DocIcon />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[13px] text-ink-1">
          <SafeText text={d.filename} />
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 font-mono text-[10.5px] text-ink-3">
          <SafeText text={d.doc_type} />
          <span>·</span>
          <span>{d.status}</span>
        </span>
      </span>
      <span className="flex-none font-mono text-[10px] tabular-nums text-ink-3">{day(d.created_at)}</span>
    </button>
  );
}

function DocPreviewModal({ docId, onClose }: { docId: string; onClose: () => void }) {
  const detail = useDocumentDetail(docId);
  const chunks = useDocumentChunks(docId, 50);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const list = chunks.data?.chunks ?? [];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-6" style={{ background: "rgba(8,10,14,0.52)" }} onClick={onClose}>
      <GlassCard className="flex max-h-[80vh] w-full max-w-2xl flex-col p-0">
        <div className="flex items-center justify-between gap-4 border-b border-[var(--card-hairline)] px-5 py-3.5" onClick={(e) => e.stopPropagation()}>
          <div className="min-w-0">
            <h2 className="truncate font-mono text-[14px] text-ink-1">
              <SafeText text={detail.data?.filename ?? "Document"} />
            </h2>
            <p className="mt-0.5 font-mono text-[10.5px] text-ink-3">{chunks.data?.total_chunks ?? list.length} chunks</p>
          </div>
          <button type="button" onClick={onClose} className="flex-none font-mono text-[12px] text-ink-2 hover:text-ink-1">
            Close
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-3" onClick={(e) => e.stopPropagation()}>
          {chunks.isPending ? (
            <div className="flex flex-col gap-3 py-2">
              {[0, 1, 2].map((i) => (
                <span key={i} className="h-[14px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${88 - i * 8}%` }} />
              ))}
            </div>
          ) : chunks.isError ? (
            <div className="py-6 text-center font-mono text-[12px] text-ink-2">Couldn't load chunks</div>
          ) : list.length === 0 ? (
            <div className="py-6 text-center font-mono text-[12px] text-ink-3">No chunks yet</div>
          ) : (
            list.map((c) => (
              <div key={c.chunk_index} className="border-b border-[var(--card-hairline)] py-3 last:border-0">
                {c.section_path && (
                  <span className="mb-1 block font-mono text-[9.5px] text-ink-3">
                    <SafeText text={c.section_path} />
                  </span>
                )}
                <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink-1">
                  <SafeText text={c.content} />
                </p>
              </div>
            ))
          )}
        </div>
      </GlassCard>
    </div>
  );
}

// ── Explorer ──────────────────────────────────────────────────────────────────
export function ExplorerView() {
  const [tab, setTab] = useState<"claims" | "documents">("claims");
  const [qRaw, setQRaw] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(qRaw), 300);
    return () => clearTimeout(t);
  }, [qRaw]);

  // Server-side filters.
  const [corroboration, setCorroboration] = useState<string | null>(null);
  const [dispute, setDispute] = useState<string | null>(null);
  const [advOpen, setAdvOpen] = useState(false);
  const [limit, setLimit] = useState<number>(50);
  const [subjectEntity, setSubjectEntity] = useState("");
  // Client-side filters.
  const [sourceType, setSourceType] = useState<string | null>(null);
  const [sensitivity, setSensitivity] = useState<string | null>(null);

  const searching = q.trim().length > 0;
  const twin = useTwinSearch(q, PROJECT_ID);
  const browse = useClaimsFiltered(PROJECT_ID, {
    corroboration_level: corroboration ?? undefined,
    dispute_state: dispute ?? undefined,
    subject_entity: subjectEntity.trim() || undefined,
    limit,
  });
  const documents = useDocuments(PROJECT_ID);
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);

  // Client-side source_type / sensitivity refinement (not server params).
  const claims = useMemo(() => {
    const rows = browse.data ?? [];
    return rows.filter((c) => (!sourceType || c.source_type === sourceType) && (!sensitivity || c.sensitivity === sensitivity));
  }, [browse.data, sourceType, sensitivity]);

  // Distinct source_type / sensitivity values present → dynamic chips (avoids
  // guessing enum values the seed may not use).
  const sourceTypes = useMemo(() => [...new Set((browse.data ?? []).map((c) => c.source_type))].sort(), [browse.data]);
  const sensitivities = useMemo(() => [...new Set((browse.data ?? []).map((c) => c.sensitivity))].sort(), [browse.data]);

  return (
    <>
      <div className="mb-[18px] mt-1.5 flex items-end justify-between gap-4 px-0.5">
        <div>
          <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Claims Explorer</h1>
          <p className="mt-1.5 text-[12.5px] text-ink-3">Browse and search the captured knowledge — ask the twin or filter the claims.</p>
        </div>
        <div className="flex gap-0.5 rounded-md p-0.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
          {(["claims", "documents"] as const).map((tb) => (
            <button
              key={tb}
              type="button"
              onClick={() => setTab(tb)}
              className={`rounded-[7px] px-3 py-1.5 font-body text-[12.5px] capitalize ${tab === tb ? "text-ink-1" : "text-ink-3"}`}
              style={tab === tb ? { background: "var(--card-bg)", boxShadow: "0 1px 2px rgba(0,0,0,0.15)" } : undefined}
            >
              {tb}
            </button>
          ))}
        </div>
      </div>

      <GlassCard className="p-4">
        {tab === "claims" ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={qRaw}
                onChange={(e) => setQRaw(e.target.value)}
                placeholder="Ask the twin…"
                className="min-w-[220px] flex-1 rounded-md px-3 py-2 font-body text-[13px] text-ink-1 outline-none"
                style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
              />
              {qRaw && (
                <button type="button" onClick={() => setQRaw("")} className="font-mono text-[11px] text-ink-3 hover:text-ink-1">
                  Clear
                </button>
              )}
            </div>

            {!searching && (
              <>
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {CORROBORATION.map((v) => (
                    <Chip key={v} active={corroboration === v} onClick={() => setCorroboration(corroboration === v ? null : v)}>
                      {v}
                    </Chip>
                  ))}
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {DISPUTE.map((v) => (
                    <Chip key={v} active={dispute === v} onClick={() => setDispute(dispute === v ? null : v)}>
                      {v}
                    </Chip>
                  ))}
                  {sourceTypes.map((v) => (
                    <Chip key={v} active={sourceType === v} onClick={() => setSourceType(sourceType === v ? null : v)}>
                      {v}
                    </Chip>
                  ))}
                  {sensitivities.map((v) => (
                    <Chip key={v} active={sensitivity === v} onClick={() => setSensitivity(sensitivity === v ? null : v)}>
                      {v}
                    </Chip>
                  ))}
                  <Chip active={advOpen} onClick={() => setAdvOpen((s) => !s)}>
                    Advanced
                  </Chip>
                </div>

                {advOpen && (
                  <div className="mt-3 flex flex-wrap items-end gap-4 rounded-md p-3" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">Limit</span>
                      <div className="flex gap-0.5 rounded-[7px] p-0.5" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                        {LIMITS.map((n) => (
                          <button key={n} type="button" onClick={() => setLimit(n)} className={`rounded-[5px] px-2 py-0.5 font-mono text-[10.5px] ${limit === n ? "text-ink-1" : "text-ink-3"}`} style={limit === n ? { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } : undefined}>
                            {n}
                          </button>
                        ))}
                      </div>
                    </div>
                    <label className="flex flex-col gap-1">
                      <span className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">Subject entity</span>
                      <input
                        value={subjectEntity}
                        onChange={(e) => setSubjectEntity(e.target.value)}
                        placeholder="e.g. Juan García"
                        className="rounded-[7px] px-2.5 py-1.5 font-mono text-[11px] text-ink-1 outline-none"
                        style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
                      />
                    </label>
                  </div>
                )}
              </>
            )}

            <div className="mt-3 max-h-[calc(100vh-320px)] overflow-y-auto">
              {searching ? (
                twin.isPending ? (
                  <Shimmer />
                ) : twin.isError ? (
                  <ErrorState onRetry={() => void twin.refetch()} />
                ) : twin.data ? (
                  <TwinAnswer answer={twin.data.answer} sources={twin.data.sources ?? []} disputes={twin.data.disputes ?? []} />
                ) : null
              ) : browse.isPending ? (
                <Shimmer />
              ) : browse.isError ? (
                <ErrorState onRetry={() => void browse.refetch()} />
              ) : claims.length === 0 ? (
                <div className="grid place-items-center py-10 font-mono text-[12.5px] text-ink-3">No claims match these filters</div>
              ) : (
                <>
                  <div className="mb-1 px-1 font-mono text-[10.5px] text-ink-3">{claims.length} claims</div>
                  {claims.map((c) => (
                    <ClaimRow key={c.id} c={c} />
                  ))}
                </>
              )}
            </div>
          </>
        ) : (
          <div className="max-h-[calc(100vh-260px)] overflow-y-auto">
            {documents.isPending ? (
              <Shimmer />
            ) : documents.isError ? (
              <ErrorState onRetry={() => void documents.refetch()} />
            ) : (documents.data ?? []).length === 0 ? (
              <div className="grid place-items-center py-10 font-mono text-[12.5px] text-ink-3">No documents uploaded</div>
            ) : (
              (documents.data ?? []).map((d) => <DocRow key={d.id} d={d} onOpen={setPreviewDocId} />)
            )}
          </div>
        )}
      </GlassCard>

      {previewDocId && <DocPreviewModal docId={previewDocId} onClose={() => setPreviewDocId(null)} />}
    </>
  );
}

function Shimmer() {
  return (
    <div className="flex flex-col gap-3 p-3">
      {[0, 1, 2, 3].map((i) => (
        <span key={i} className="h-[14px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${88 - i * 8}%` }} />
      ))}
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <span className="h-[7px] w-[7px] rounded-full" style={{ background: "var(--red)", boxShadow: "0 0 6px rgba(222,70,48,0.5)" }} />
      <span className="font-mono text-[12px] text-ink-2">Something went wrong</span>
      <button type="button" onClick={onRetry} className="font-mono text-[12px] text-ink-1 underline underline-offset-2">
        Retry
      </button>
    </div>
  );
}
