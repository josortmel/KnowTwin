import { useMemo, useRef, useState } from "react";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { SafeText } from "../../components/SafeText";
import { pushToast } from "../../lib/toast";
import {
  useDocuments,
  useDocumentDetail,
  useDocumentChunks,
  useReindexDocument,
  useDeleteDocument,
  useUploadDocument,
  type Document,
} from "../../hooks/useDocuments";
import { useKnowledgeStats } from "../../hooks/useDashboard";

const PROJECT_ID = 1;
// Ingestion hue: cyan (--sec-ingestion #5BAAB5), distinct from the Graph teal.
const ACCENT = "var(--sec-ingestion)";
const TRUST_HINTS = ["formal_contract", "adr", "signed_plan", "wiki", "presentation", "email", "orgchart", "other"];
const CELL = { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } as const;

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

// REST `status` colors (persisted vocabulary). Match loosely so an unseen value
// still lands on a sensible color instead of breaking. Dot-only signal (§1.3).
function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (s.includes("index")) return "var(--grn)";
  if (s.includes("fail") || s.includes("error")) return "var(--red)";
  if (s.includes("dup")) return "var(--sec-setup)"; // amber
  if (s.includes("process") || s.includes("pending") || s.includes("queue")) return "var(--accent)";
  return "var(--ink-3)";
}

function relativeAge(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

function StatusDot({ color, size = 6 }: { color: string; size?: number }) {
  return (
    <span className="grid h-[14px] w-[14px] flex-none place-items-center rounded-full" style={CELL}>
      <span className="rounded-full" style={{ width: size, height: size, background: color, boxShadow: `0 0 6px ${color}` }} />
    </span>
  );
}

function MetricTile({ label, value, sub, color, loading }: { label: string; value: string; sub: string; color: string; loading?: boolean }) {
  return (
    <GlassCard className="p-4">
      <div className="flex items-center gap-2">
        <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
        <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-3">{label}</span>
      </div>
      <div className="mt-2 font-mono text-[26px] font-medium leading-none tabular-nums text-ink-1">
        {loading ? <span className="inline-block h-[20px] w-[40px] animate-pulse rounded-sm align-middle" style={{ background: "var(--inset)" }} /> : value}
      </div>
      <div className="mt-1.5 font-mono text-[10px] text-ink-3">{sub}</div>
    </GlassCard>
  );
}

function DocRow({ doc, active, onClick }: { doc: Document; active: boolean; onClick: () => void }) {
  const color = statusColor(doc.status);
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      className="grid w-full grid-cols-[16px_1fr_auto] items-center gap-3 border-b border-[var(--card-hairline)] px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-[var(--inset)]"
      style={active ? { background: "color-mix(in srgb, var(--sec-ingestion) 12%, transparent)" } : undefined}
    >
      <StatusDot color={color} />
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] text-ink-1">
          <SafeText text={doc.filename} />
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[0.06em] text-ink-3">
          <span className="text-ink-3">{doc.status}</span>
          <span>·</span>
          <SafeText text={doc.doc_type} />
        </span>
      </span>
      <span className="flex-none font-mono text-[10px] tabular-nums text-ink-3">{doc.created_at.slice(0, 10)}</span>
    </button>
  );
}

function MetaCell({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-md p-2.5" style={CELL}>
      <div className="truncate font-mono text-[12px] text-ink-1">
        <SafeText text={v} />
      </div>
      <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">{k}</div>
    </div>
  );
}

function DocDetailPanel({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const detail = useDocumentDetail(id);
  const chunks = useDocumentChunks(id, 20);
  const reindex = useReindexDocument();
  const del = useDeleteDocument();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const d = detail.data;
  const busy = reindex.isPending || del.isPending;
  const color = d ? statusColor(d.status) : ACCENT;

  const onReindex = () =>
    reindex.mutate(id, {
      onSuccess: () => pushToast("Reindex triggered", { tone: "success" }),
      onError: (e) => pushToast(`Reindex failed: ${errMsg(e)}`, { tone: "error" }),
    });
  const onDelete = () =>
    del.mutate(id, {
      onSuccess: () => {
        pushToast("Document deleted", { tone: "success" });
        onDeleted();
      },
      onError: (e) => {
        setConfirmDelete(false);
        pushToast(`Delete failed: ${errMsg(e)}`, { tone: "error" });
      },
    });

  if (detail.isPending) {
    return (
      <div className="flex flex-col gap-2.5 p-1">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-[14px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${80 - i * 10}%` }} />
        ))}
      </div>
    );
  }
  if (detail.isError || !d) {
    return <div className="grid h-full place-items-center px-6 text-center font-mono text-[12px] text-ink-3">Couldn't load this document.</div>;
  }

  const previewChunks = chunks.data?.chunks ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2">
        <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
        {d.status}
      </div>
      <div className="mt-2 break-words text-[16px] font-semibold leading-tight text-ink-1">
        <SafeText text={d.filename} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <MetaCell k="Type" v={d.doc_type} />
        <MetaCell k="Visibility" v={d.visibility} />
        <MetaCell k="Created" v={new Date(d.created_at).toLocaleString("en-US", { hour12: false })} />
        <MetaCell k="Last indexed" v={d.last_indexed ? new Date(d.last_indexed).toLocaleString("en-US", { hour12: false }) : "—"} />
        <MetaCell k="Retries" v={String(d.retry_count)} />
        <MetaCell k="Trust hint" v={d.trust_hint ? d.trust_hint.replace(/_/g, " ") : "—"} />
      </div>
      <div className="mt-2.5">
        <MetaCell k="Document ID" v={d.id} />
      </div>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Chunks</span>
          {chunks.data && <span className="font-mono text-[10px] tabular-nums text-ink-3">{chunks.data.total_chunks} total</span>}
        </div>
        {chunks.isPending ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <span key={i} className="h-[28px] animate-pulse rounded-md" style={{ background: "var(--inset)" }} />
            ))}
          </div>
        ) : previewChunks.length === 0 ? (
          <div className="font-mono text-[11.5px] text-ink-3">No chunks yet — the document may still be processing.</div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {previewChunks.map((c) => (
              <div key={c.chunk_index} className="rounded-md p-2.5" style={CELL}>
                <div className="flex items-center justify-between font-mono text-[9.5px] text-ink-3">
                  <span>#{c.chunk_index}</span>
                  {c.section_path && (
                    <span className="truncate">
                      <SafeText text={c.section_path} />
                    </span>
                  )}
                </div>
                <div className="mt-1 line-clamp-3 text-[11.5px] leading-snug text-ink-2">
                  <SafeText text={c.content} />
                </div>
              </div>
            ))}
            {chunks.data?.truncated && (
              <div className="px-1 font-mono text-[10px] text-ink-3">+{chunks.data.total_chunks - previewChunks.length} more chunks</div>
            )}
          </div>
        )}
      </div>

      <div className="mt-5 flex flex-none items-stretch gap-2.5">
        {confirmDelete ? (
          <>
            <span className="flex flex-1 items-center font-mono text-[11px] text-ink-1">Delete document + chunks? Can't be undone.</span>
            <Button variant="danger" onClick={onDelete} loading={del.isPending} className="px-3.5 py-2.5 text-[12px]">
              Delete
            </Button>
            <Button variant="default" onClick={() => setConfirmDelete(false)} disabled={del.isPending} className="px-3.5 py-2.5 text-[12px]">
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button variant="primary" onClick={onReindex} loading={reindex.isPending} disabled={busy} className="flex-1 py-2.5 text-[12.5px]">
              Reindex
            </Button>
            <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={busy} className="px-4 py-2.5 text-[12.5px]">
              Delete
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

export function IngestionView() {
  const docsQ = useDocuments(PROJECT_ID);
  const knowledge = useKnowledgeStats();
  const upload = useUploadDocument();
  const fileRef = useRef<HTMLInputElement>(null);
  const [trustHint, setTrustHint] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const docs = docsQ.data ?? [];
  const counts = useMemo(() => {
    const c = { indexed: 0, duplicate: 0, failed: 0 };
    for (const d of docs) {
      if (d.status === "indexed") c.indexed++;
      else if (d.status === "duplicate") c.duplicate++;
      else if (d.status === "failed") c.failed++;
    }
    return c;
  }, [docs]);
  const dupCandidates = knowledge.data?.duplicate_candidate_count;

  // Live activity — no SSE wired; useDocuments already polls while any doc is
  // non-terminal, so the newest docs surface here as they move through stages.
  const recent = useMemo(() => [...docs].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 6), [docs]);

  const onPickFile = () => {
    if (upload.isPending) return;
    fileRef.current?.click();
  };
  const onFile = () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    upload.mutate(
      { file, projectId: PROJECT_ID, trustHint: trustHint || undefined },
      {
        onSuccess: () => pushToast("Document uploaded — indexing…", { tone: "success" }),
        onError: (e) => pushToast(`Upload failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <>
      <div className="mb-[18px] mt-1.5 flex flex-wrap items-end justify-between gap-4 px-0.5">
        <div>
          <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Ingestion</h1>
          <p className="mt-1.5 text-[12.5px] text-ink-3">Upload source documents, watch them index, and inspect their chunks.</p>
        </div>
        <div className="flex flex-none items-center gap-2">
          <select
            value={trustHint}
            onChange={(e) => setTrustHint(e.target.value)}
            aria-label="Trust hint"
            className="h-11 rounded-md px-2.5 font-mono text-[12px] text-ink-1 outline-none"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          >
            <option value="">Trust hint…</option>
            {TRUST_HINTS.map((h) => (
              <option key={h} value={h}>
                {h.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <input ref={fileRef} type="file" className="hidden" onChange={onFile} />
          <Button variant="primary" onClick={onPickFile} loading={upload.isPending} className="h-11 px-3.5 text-[12.5px]">
            <span className="inline-flex items-center gap-2">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={15} height={15} aria-hidden="true">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
              Add document
            </span>
          </Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile label="Indexed" value={String(counts.indexed)} sub="documents live" color="var(--grn)" loading={docsQ.isPending} />
        <MetricTile label="Duplicates" value={String(counts.duplicate)} sub="detected" color="var(--sec-setup)" loading={docsQ.isPending} />
        <MetricTile label="Failed" value={String(counts.failed)} sub="need attention" color="var(--red)" loading={docsQ.isPending} />
        <MetricTile
          label="Dup candidates"
          value={dupCandidates != null ? dupCandidates.toLocaleString("en-US") : "—"}
          sub="from graph stats"
          color={ACCENT}
          loading={knowledge.isPending}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        {/* LEFT: live activity (top) + historical documents (bottom) */}
        <div className="flex max-h-[calc(100vh-360px)] flex-col gap-4">
          <GlassCard className="flex max-h-[210px] flex-col p-3">
            <div className="mb-2 flex flex-none items-center justify-between gap-2 px-1">
              <div className="flex items-center gap-2">
                <span className="h-[7px] w-[7px] rounded-full motion-safe:animate-pulse" style={{ background: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
                <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Live Activity</span>
              </div>
              <span className="font-mono text-[9.5px] tracking-[0.04em] text-ink-3">polling</span>
            </div>
            {docsQ.isPending ? (
              <div className="flex flex-col gap-2 p-2">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="h-[16px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${88 - i * 10}%` }} />
                ))}
              </div>
            ) : recent.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-8 py-6 text-center">
                <span className="font-mono text-[12px] text-ink-2">Nothing ingesting</span>
                <span className="max-w-[340px] text-[11px] leading-relaxed text-ink-3">Add a document to see it move through the pipeline here.</span>
              </div>
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto">
                {recent.map((doc) => {
                  const color = statusColor(doc.status);
                  return (
                    <div key={doc.id} className="grid w-full grid-cols-[16px_1fr_auto] items-center gap-3 border-b border-[var(--card-hairline)] px-3 py-2 last:border-0">
                      <StatusDot color={color} />
                      <span className="min-w-0">
                        <span className="block truncate text-[12.5px] text-ink-1">
                          <SafeText text={doc.filename} />
                        </span>
                        <span className="font-mono text-[9.5px] uppercase tracking-[0.06em] text-ink-3">
                          {doc.status}
                        </span>
                      </span>
                      <span className="flex-none font-mono text-[10px] tabular-nums text-ink-3">{relativeAge(doc.created_at)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </GlassCard>

          <GlassCard className="flex min-h-0 flex-1 flex-col p-3">
            <div className="mb-2 flex flex-none items-center justify-between gap-2 px-1">
              <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Documents</span>
              {docsQ.data && <span className="font-mono text-[9.5px] tabular-nums text-ink-3">{docs.length} total</span>}
            </div>
            {docsQ.isPending ? (
              <div className="flex flex-col gap-2 p-2">
                {[0, 1, 2, 3].map((i) => (
                  <span key={i} className="h-[16px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${90 - i * 8}%` }} />
                ))}
              </div>
            ) : docsQ.isError ? (
              <div className="grid flex-1 place-items-center px-8 text-center">
                <div className="flex flex-col items-center gap-2">
                  <span className="h-[7px] w-[7px] rounded-full" style={{ background: "var(--red)", boxShadow: "0 0 6px rgba(222,70,48,0.5)" }} />
                  <span className="font-mono text-[12px] text-ink-2">Couldn't load documents</span>
                  <button type="button" onClick={() => void docsQ.refetch()} className="font-mono text-[12px] text-accent underline underline-offset-2">
                    Retry
                  </button>
                </div>
              </div>
            ) : docs.length === 0 ? (
              <div className="grid flex-1 place-items-center px-8 text-center font-mono text-[12px] text-ink-3">No documents uploaded yet</div>
            ) : (
              <div role="listbox" aria-label="Documents" className="min-h-0 flex-1 overflow-y-auto">
                {docs.map((doc) => (
                  <DocRow key={doc.id} doc={doc} active={selectedId === doc.id} onClick={() => setSelectedId(doc.id)} />
                ))}
              </div>
            )}
          </GlassCard>
        </div>

        {/* RIGHT: detail of the selected document */}
        <GlassCard className="flex max-h-[calc(100vh-360px)] flex-col p-[18px]">
          {selectedId ? (
            <DocDetailPanel key={selectedId} id={selectedId} onDeleted={() => setSelectedId(null)} />
          ) : (
            <div className="grid h-full place-items-center px-6 text-center font-mono text-[12px] text-ink-3">Select a document to inspect its chunks.</div>
          )}
        </GlassCard>
      </div>
    </>
  );
}
