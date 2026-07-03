import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { SafeText } from "../../components/SafeText";
import { pushToast } from "../../lib/toast";
import { get } from "../../lib/api";
import { useMe } from "../../hooks/useScore";
import {
  useGraphVocabulary,
  useEntityDictionary,
  useStopEntities,
  useCreateEntity,
  useUpdateEntity,
  useDeleteEntity,
  useReloadDictionary,
  useCreateStopEntity,
  useDeleteStopEntity,
  useCreatePredicate,
  useUpdatePredicate,
  useDeletePredicate,
  useMergeEntities,
  useUndoMerge,
  useAliasCandidates,
  useScanAliases,
  useReviewAlias,
  type Predicate,
  type EntityEntry,
  type AliasItem,
} from "../../hooks/useOntology";

const ACCENT = "var(--sec-ontology)";
const PREDICATE_STATES = ["experimental", "candidate", "approved", "deprecated", "archived", "forbidden"] as const;
const FIELD = { background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } as const;
const CELL = { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } as const;

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

interface NodeMatch {
  id: number;
  name: string;
  similarity?: number;
}
async function searchNodes(q: string, limit: number): Promise<NodeMatch[]> {
  const r = await get<{ matches: NodeMatch[] }>(`/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`);
  return r.matches ?? [];
}

type VocabEntity = { name: string; type: string };
const entityKey = (e: VocabEntity): string => `${e.type}:${e.name}`;

function TextInput({ value, onChange, placeholder, onEnter }: { value: string; onChange: (v: string) => void; placeholder: string; onEnter?: () => void }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onEnter ? (e) => { if (e.key === "Enter") { e.preventDefault(); onEnter(); } } : undefined}
      placeholder={placeholder}
      className="w-full rounded-md px-3 py-2 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
      style={FIELD}
    />
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  // §1.3: active via tint+border, never colored text.
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-[20px] px-2.5 py-1 font-mono text-[10px] transition-colors ${active ? "text-ink-1" : "text-ink-3 hover:text-ink-1"}`}
      style={active ? { background: "color-mix(in srgb, var(--sec-ontology) 14%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-ontology) 38%, transparent)" } : { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
    >
      {children}
    </button>
  );
}

function SmallDanger({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="flex-none rounded-sm px-2 py-1 font-mono text-[10.5px] text-ink-1 disabled:opacity-50" style={{ background: "color-mix(in srgb, var(--red) 12%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 38%, transparent)" }}>
      {children}
    </button>
  );
}

function StateWrap({ query, isAdmin, children }: { query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; isAdmin: boolean; children: ReactNode }) {
  const is403 = /403/.test(query.error instanceof Error ? query.error.message : "");
  if (!isAdmin || is403) return <div className="grid place-items-center py-16 font-mono text-[12.5px] text-ink-3">This console is limited to curators and admins.</div>;
  if (query.isPending)
    return (
      <div className="flex flex-col gap-2.5 py-2">
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className="h-[13px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${90 - i * 8}%` }} />
        ))}
      </div>
    );
  if (query.isError)
    return (
      <div className="flex flex-col items-center gap-2 py-12 text-center">
        <span className="h-[7px] w-[7px] rounded-full" style={{ background: "var(--red)", boxShadow: "0 0 6px rgba(222,70,48,0.5)" }} />
        <span className="font-mono text-[12px] text-ink-2">Something went wrong</span>
        <button type="button" onClick={() => void query.refetch()} className="font-mono text-[12px] text-ink-1 underline underline-offset-2">
          Retry
        </button>
      </div>
    );
  return <>{children}</>;
}

// ── Entity detail: MERGE FLOW (pick → confirm → merge → undo) ──────────────────
function EntityDetail({ entity }: { entity: VocabEntity }) {
  const merge = useMergeEntities();
  const undo = useUndoMerge();
  const [mode, setMode] = useState<"view" | "pick" | "confirm">("view");
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<NodeMatch[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [target, setTarget] = useState<NodeMatch | null>(null);
  const [keepAlias, setKeepAlias] = useState(false);
  const [mergedId, setMergedId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = merge.isPending || undo.isPending;

  const load = async (q: string) => {
    setSearching(true);
    try {
      const res = await searchNodes(q, 8);
      setMatches(res.filter((m) => m.name.toLowerCase() !== entity.name.toLowerCase()));
    } catch {
      setMatches([]);
    } finally {
      setSearched(true);
      setSearching(false);
    }
  };
  const startMerge = () => {
    setError(null);
    setMode("pick");
    setQuery("");
    setTarget(null);
    setKeepAlias(false);
    setMatches([]);
    setSearched(false);
    void load(entity.name);
  };
  const cancelMerge = () => {
    setMode("view");
    setTarget(null);
    setKeepAlias(false);
    setError(null);
  };

  const doMerge = async () => {
    if (!target || submitting) return;
    setError(null);
    setSubmitting(true);
    let sourceId: number | undefined;
    try {
      const src = await searchNodes(entity.name, 8);
      // Require EXACTLY one exact-name match — never merge a fuzzy/renamed node.
      const exact = src.filter((m) => m.name.toLowerCase() === entity.name.toLowerCase());
      if (exact.length === 1) sourceId = exact[0].id;
    } catch {
      /* handled below */
    }
    if (sourceId == null) {
      setError("Couldn't resolve this entity to a single graph node — aborting.");
      setSubmitting(false);
      return;
    }
    if (sourceId === target.id) {
      setError("Source and target are the same node.");
      setSubmitting(false);
      return;
    }
    const src = sourceId;
    merge.mutate(
      { source_node_id: src, target_node_id: target.id, keep_as_alias: keepAlias },
      {
        onSuccess: () => {
          setMergedId(src);
          pushToast(`Merged ${entity.name} → ${target.name}`, { tone: "success" });
          cancelMerge();
          setSubmitting(false);
        },
        onError: (e) => {
          setError(`Merge failed: ${errMsg(e)}`);
          setSubmitting(false);
        },
      },
    );
  };
  const doUndo = () => {
    if (mergedId == null) return;
    undo.mutate(mergedId, {
      onSuccess: () => {
        pushToast("Merge undone", { tone: "success" });
        setMergedId(null);
      },
      onError: (e) => pushToast(`Undo failed: ${errMsg(e)}`, { tone: "error" }),
    });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2">
        <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: ACCENT, boxShadow: `0 0 8px ${ACCENT}` }} />
        <SafeText text={entity.type} />
      </div>
      <div className="mt-2 break-words text-[18px] font-semibold leading-tight text-ink-1">
        <SafeText text={entity.name} />
      </div>

      {mode === "pick" && (
        <div className="mt-4 flex min-h-0 flex-1 flex-col">
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Merge {entity.name} into…</div>
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <TextInput value={query} onChange={setQuery} placeholder="Search target entity…" onEnter={() => query.trim().length >= 3 && void load(query)} />
            </div>
            <button type="button" onClick={() => query.trim().length >= 3 && void load(query)} disabled={searching} className="flex-none rounded-md px-3 py-2 font-mono text-[11px] text-ink-1 transition-colors hover:bg-[var(--inset)] disabled:opacity-50" style={FIELD}>
              {searching ? "…" : "Search"}
            </button>
          </div>
          <div className="mt-2 min-h-0 flex-1 overflow-y-auto">
            {searched && matches.length === 0 ? (
              <div className="px-1 py-3 font-mono text-[11.5px] text-ink-3">No matches</div>
            ) : (
              matches.map((m) => (
                <button key={m.id} type="button" onClick={() => { setTarget(m); setMode("confirm"); }} className="flex w-full items-center gap-2 border-b border-[var(--card-hairline)] px-2.5 py-2 text-left transition-colors last:border-0 hover:bg-[var(--inset)]">
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-1">
                    <SafeText text={m.name} />
                  </span>
                  {m.similarity != null && <span className="flex-none font-mono text-[9.5px] tabular-nums text-ink-3">{m.similarity.toFixed(2)}</span>}
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {mode !== "pick" && <div className="flex-1" />}

      {error && (
        <div className="mb-2.5 flex items-start gap-2 rounded-md px-3 py-2" style={{ background: "color-mix(in srgb, var(--red) 10%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 30%, transparent)" }}>
          <span className="mt-[3px] h-[6px] w-[6px] flex-none rounded-full" style={{ background: "var(--red)" }} />
          <span className="text-[11.5px] leading-relaxed text-ink-1">{error}</span>
        </div>
      )}

      {mode === "confirm" && target ? (
        <div className="flex flex-col gap-2.5">
          <span className="font-mono text-[11.5px] leading-relaxed text-ink-1">
            Merge <SafeText text={entity.name} /> into <SafeText text={target.name} />? This cannot be undone from here.
          </span>
          <label className="flex cursor-pointer items-start gap-2 font-mono text-[11px] leading-relaxed text-ink-2">
            <input type="checkbox" checked={keepAlias} onChange={(e) => setKeepAlias(e.target.checked)} className="mt-0.5 flex-none" style={{ accentColor: "var(--sec-ontology)" }} />
            <span>Keep {entity.name} as an alias of {target.name}</span>
          </label>
          <div className="flex gap-2.5">
            <Button variant="primary" onClick={() => void doMerge()} loading={submitting} className="flex-1 py-2.5 text-[12.5px]">
              Confirm merge
            </Button>
            <Button variant="default" onClick={() => setMode("pick")} disabled={submitting} className="px-4 py-2.5 text-[12px]">
              Back
            </Button>
          </div>
        </div>
      ) : mode === "pick" ? (
        <Button variant="default" onClick={cancelMerge} className="mt-2 px-4 py-2 text-[12px]">
          Cancel
        </Button>
      ) : mergedId != null ? (
        <div className="flex items-center gap-2.5">
          <span className="flex-1 font-mono text-[11.5px] text-ink-2">Merged. You can undo this while it's fresh.</span>
          <Button variant="default" onClick={doUndo} loading={undo.isPending} className="px-4 py-2.5 text-[12px]">
            Undo
          </Button>
        </div>
      ) : (
        <Button variant="primary" onClick={startMerge} disabled={busy} className="w-full py-2.5 text-[12.5px]">
          Merge…
        </Button>
      )}
    </div>
  );
}

// ── Entities tab ──────────────────────────────────────────────────────────────
function EntitiesTab({ isAdmin }: { isAdmin: boolean }) {
  const vocab = useGraphVocabulary();
  const dict = useEntityDictionary();
  const stop = useStopEntities();
  const [type, setType] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const entities: VocabEntity[] = vocab.data?.entities ?? [];
  const types = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of entities) m.set(e.type, (m.get(e.type) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [entities]);
  const dictSet = useMemo(() => new Set((dict.data ?? []).map((d) => d.name.toLowerCase())), [dict.data]);
  const stopSet = useMemo(() => new Set((stop.data ?? []).map((s) => s.name.toLowerCase())), [stop.data]);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return entities.filter((e) => (!type || e.type === type) && (!needle || e.name.toLowerCase().includes(needle)));
  }, [entities, type, q]);
  const selected = filtered.find((e) => entityKey(e) === selectedKey) ?? filtered[0] ?? null;

  return (
    <StateWrap query={vocab} isAdmin={isAdmin}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <GlassCard className="flex max-h-[calc(100vh-250px)] flex-col p-3">
          <TextInput value={q} onChange={setQ} placeholder="Search entities…" />
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <Chip active={type === null} onClick={() => setType(null)}>
              All
            </Chip>
            {types.map(([ty, n]) => (
              <Chip key={ty} active={type === ty} onClick={() => setType(type === ty ? null : ty)}>
                {ty} <span className="text-ink-3">{n}</span>
              </Chip>
            ))}
          </div>
          <div className="mt-2 px-1 font-mono text-[10px] text-ink-3">{filtered.length} shown</div>
          <div role="listbox" className="mt-1 min-h-0 flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="grid place-items-center py-10 font-mono text-[12px] text-ink-3">No entities</div>
            ) : (
              filtered.map((e) => {
                const active = !!selected && entityKey(selected) === entityKey(e);
                return (
                  <button key={entityKey(e)} type="button" onClick={() => setSelectedKey(entityKey(e))} className="flex w-full items-center gap-2.5 border-b border-[var(--card-hairline)] px-2.5 py-2.5 text-left transition-colors last:border-0 hover:bg-[var(--inset)]" style={active ? { background: "color-mix(in srgb, var(--sec-ontology) 12%, transparent)" } : undefined}>
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-1">
                      <SafeText text={e.name} />
                    </span>
                    {dictSet.has(e.name.toLowerCase()) && <span className="flex-none rounded-sm px-1.5 py-0.5 font-mono text-[9px] text-ink-2" style={{ background: "color-mix(in srgb, var(--sec-explorer) 12%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-explorer) 32%, transparent)" }}>dict</span>}
                    {stopSet.has(e.name.toLowerCase()) && <span className="flex-none rounded-sm px-1.5 py-0.5 font-mono text-[9px] text-ink-2" style={{ background: "color-mix(in srgb, var(--red) 12%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 32%, transparent)" }}>stop</span>}
                    <span className="flex-none font-mono text-[9.5px] text-ink-3">{e.type}</span>
                  </button>
                );
              })
            )}
          </div>
        </GlassCard>

        <GlassCard className="flex max-h-[calc(100vh-250px)] flex-col p-[18px]">
          {selected ? <EntityDetail key={entityKey(selected)} entity={selected} /> : <div className="grid h-full place-items-center px-6 text-center font-mono text-[12px] text-ink-3">Select an entity to inspect or merge it.</div>}
        </GlassCard>
      </div>
    </StateWrap>
  );
}

// ── Predicates tab (grouped by cluster) ───────────────────────────────────────
function PredicatesTab({ isAdmin }: { isAdmin: boolean }) {
  const vocab = useGraphVocabulary();
  const create = useCreatePredicate();
  const update = useUpdatePredicate();
  const del = useDeletePredicate();
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [cluster, setCluster] = useState("");
  const [pstate, setPstate] = useState<string>("approved");
  const [confirmName, setConfirmName] = useState<string | null>(null);

  const predicates: Predicate[] = vocab.data?.predicates ?? [];
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return predicates.filter((p) => !needle || p.name.toLowerCase().includes(needle) || p.description.toLowerCase().includes(needle));
  }, [predicates, q]);
  const grouped = useMemo(() => {
    const m = new Map<string, Predicate[]>();
    for (const p of filtered) {
      const c = p.cluster || "uncategorized";
      const arr = m.get(c) ?? [];
      arr.push(p);
      m.set(c, arr);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered]);
  const busy = create.isPending || update.isPending;

  const reset = () => {
    setEditing(null);
    setName("");
    setDesc("");
    setCluster("");
    setPstate("approved");
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    const onErr = (err: unknown) => pushToast(`Predicate failed: ${errMsg(err)}`, { tone: "error" });
    if (editing) update.mutate({ name: editing, body: { description: desc.trim(), cluster: cluster.trim() || undefined, state: pstate } }, { onSuccess: reset, onError: onErr });
    else create.mutate({ name: name.trim(), description: desc.trim(), cluster: cluster.trim() || undefined, state: pstate }, { onSuccess: reset, onError: onErr });
  };
  const onEdit = (p: Predicate) => {
    setEditing(p.name);
    setName(p.name);
    setDesc(p.description);
    setCluster(p.cluster ?? "");
    setPstate(p.state ?? "approved");
  };
  const onDelete = (n: string) => {
    if (confirmName !== n) return setConfirmName(n);
    del.mutate(n, { onSuccess: () => setConfirmName(null), onError: (err) => { setConfirmName(null); pushToast(`Delete failed: ${errMsg(err)}`, { tone: "error" }); } });
  };

  return (
    <StateWrap query={vocab} isAdmin={isAdmin}>
      <GlassCard className="flex max-h-[calc(100vh-250px)] flex-col p-3">
        <form onSubmit={onSubmit} className="mb-2.5 flex flex-wrap items-center gap-2">
          <div className="min-w-[120px] flex-1">
            <input value={name} onChange={(e) => !editing && setName(e.target.value)} readOnly={!!editing} placeholder="predicate_name" className="w-full rounded-md px-3 py-2 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3" style={FIELD} />
          </div>
          <div className="min-w-[150px] flex-[1.5]">
            <TextInput value={desc} onChange={setDesc} placeholder="Description" />
          </div>
          <div className="min-w-[90px] flex-1">
            <TextInput value={cluster} onChange={setCluster} placeholder="Cluster" />
          </div>
          <select value={pstate} onChange={(e) => setPstate(e.target.value)} className="flex-none rounded-md px-2 py-2 font-mono text-[11px] text-ink-1" style={FIELD}>
            {PREDICATE_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <Button variant="primary" type="submit" disabled={busy || !name.trim()} className="px-4 py-2 text-[12px]">
            {editing ? "Update" : "Add"}
          </Button>
          {editing && (
            <button type="button" onClick={reset} className="flex-none rounded-btn px-3 py-2 font-mono text-[11px] text-ink-2" style={CELL}>
              Cancel
            </button>
          )}
        </form>
        <TextInput value={q} onChange={setQ} placeholder="Search predicates…" />
        <div className="mt-2 px-1 font-mono text-[10px] text-ink-3">{filtered.length} shown</div>
        <div className="mt-1 min-h-0 flex-1 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="grid place-items-center py-10 font-mono text-[12px] text-ink-3">No predicates</div>
          ) : (
            grouped.map(([clusterName, preds]) => (
              <div key={clusterName} className="mb-2">
                <div className="sticky top-0 bg-[var(--card-bg)] px-2.5 py-1 font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">{clusterName} · {preds.length}</div>
                {preds.map((p) => (
                  <div key={p.name} className="flex items-center gap-3 border-b border-[var(--card-hairline)] px-2.5 py-2.5 last:border-0">
                    <span className="h-[6px] w-[6px] flex-none rounded-full" style={{ background: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
                    <span className="flex-none truncate font-mono text-[12.5px] text-ink-1" style={{ maxWidth: 180 }}>
                      <SafeText text={p.name} />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">
                      <SafeText text={p.description} />
                    </span>
                    {p.state && p.state !== "approved" && <span className="flex-none font-mono text-[9px] text-ink-3">{p.state}</span>}
                    <button type="button" onClick={() => onEdit(p)} className="flex-none rounded-sm px-2 py-1 font-mono text-[10.5px] text-ink-2" style={CELL}>
                      Edit
                    </button>
                    <SmallDanger onClick={() => onDelete(p.name)} disabled={del.isPending}>
                      {confirmName === p.name ? "Confirm?" : "Delete"}
                    </SmallDanger>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </GlassCard>
    </StateWrap>
  );
}

// ── Alias scan panel ──────────────────────────────────────────────────────────
function AliasScanPanel() {
  const scan = useScanAliases();
  const [threshold, setThreshold] = useState(0.65);
  const [maxPerName, setMaxPerName] = useState(3);
  const [nameFilter, setNameFilter] = useState("");
  const [result, setResult] = useState<{ res: Awaited<ReturnType<typeof scan.mutateAsync>>; preview: boolean } | null>(null);
  const [lastOp, setLastOp] = useState<"preview" | "scan" | null>(null);
  const busy = scan.isPending;

  const run = (dry: boolean) => {
    if (busy) return;
    setLastOp(dry ? "preview" : "scan");
    setResult(null);
    scan.mutate(
      { threshold, max_per_name: maxPerName, ...(nameFilter.trim() ? { name_filter: nameFilter.trim() } : {}), dry_run: dry },
      {
        onSuccess: (res) => {
          setResult({ res, preview: dry });
          if (!dry) pushToast(`Scan: ${res.found} found · ${res.inserted} inserted`, { tone: "success" });
        },
        onError: (e) => pushToast(`Scan failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };
  const preview = result?.res.candidates ?? [];

  return (
    <GlassCard className="flex flex-col gap-3 p-3">
      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2">
        <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: ACCENT, boxShadow: `0 0 8px ${ACCENT}` }} />
        Retroactive alias scan
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3">Threshold</span>
          <span className="font-mono text-[13px] tabular-nums text-ink-1">{threshold.toFixed(2)}</span>
        </div>
        <input type="range" min={0} max={1} step={0.01} value={threshold} onChange={(e) => setThreshold(parseFloat(e.target.value))} className="w-full" style={{ accentColor: "var(--sec-ontology)" }} />
        <span className="font-mono text-[9.5px] text-ink-3">{threshold < 0.6 ? "Low threshold — expect noisy matches." : "Higher = stricter matching."}</span>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3">Max per name</span>
          <input type="number" min={1} max={10} value={maxPerName} onChange={(e) => setMaxPerName(Math.min(10, Math.max(1, Math.round(Number(e.target.value) || 1))))} className="w-[64px] rounded-md px-2.5 py-2 font-mono text-[12px] text-ink-1 outline-none" style={FIELD} />
        </div>
        <div className="min-w-[140px] flex-1">
          <TextInput value={nameFilter} onChange={setNameFilter} placeholder="Name filter (optional)" />
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="default" onClick={() => run(true)} loading={busy && lastOp === "preview"} disabled={busy} className="px-3.5 py-2 text-[12px]">
          Preview
        </Button>
        <Button variant="primary" onClick={() => run(false)} loading={busy && lastOp === "scan"} disabled={busy} className="px-4 py-2 text-[12px]">
          Run scan
        </Button>
      </div>
      {result && (
        <div className="flex flex-col gap-1.5 rounded-md p-2.5" style={CELL}>
          <span className="font-mono text-[11.5px] text-ink-1">
            {result.preview ? "Preview" : "Scan"}: {result.res.found} found · {result.res.inserted} inserted · {result.res.updated} updated
          </span>
          <span className="font-mono text-[10px] text-ink-3">{result.res.total_pending} pending total</span>
          {result.preview &&
            preview.slice(0, 6).map((c, i) => (
              <div key={`${c.source_name}-${c.target_node_id}-${i}`} className="flex items-center gap-1.5 font-mono text-[10.5px] text-ink-2">
                <span className="min-w-0 truncate">
                  <SafeText text={c.source_name} />
                </span>
                <span className="flex-none text-ink-3">→</span>
                <span className="min-w-0 truncate">
                  <SafeText text={c.target_node_name ?? `#${c.target_node_id}`} />
                </span>
                <span className="flex-none tabular-nums text-ink-3">{c.confidence.toFixed(2)}</span>
              </div>
            ))}
        </div>
      )}
    </GlassCard>
  );
}

// ── Aliases tab ───────────────────────────────────────────────────────────────
function AliasesTab({ isAdmin }: { isAdmin: boolean }) {
  const [status, setStatus] = useState("pending");
  const aliases = useAliasCandidates(status, 50);
  const review = useReviewAlias();
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [reverse, setReverse] = useState(false);
  const items: AliasItem[] = aliases.data ?? [];
  const isPending = status === "pending";
  const acting = review.isPending;

  const onReview = (id: number, st: "approved" | "rejected", merge?: boolean, rev?: boolean) =>
    review.mutate(
      { id, status: st, ...(merge != null ? { merge } : {}), ...(rev != null ? { reverse: rev } : {}) },
      { onSuccess: () => { pushToast("Alias reviewed", { tone: "success" }); setConfirmId(null); }, onError: (e) => pushToast(`Review failed: ${errMsg(e)}`, { tone: "error" }) },
    );

  return (
    <StateWrap query={aliases} isAdmin={isAdmin}>
      <div className="flex flex-col gap-4">
        <div className="flex gap-1.5">
          {["pending", "approved"].map((s) => (
            <Chip key={s} active={status === s} onClick={() => { setStatus(s); setConfirmId(null); setReverse(false); }}>
              {s}
            </Chip>
          ))}
        </div>
        {isPending && <AliasScanPanel />}
        <GlassCard className="flex max-h-[calc(100vh-340px)] flex-col p-3">
          {items.length === 0 ? (
            <div className="grid place-items-center py-12 font-mono text-[12.5px] text-ink-3">{isPending ? "No pending alias candidates" : "No resolved aliases"}</div>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              {items.map((a) => {
                const survivor = reverse ? a.source_name : a.target_node_name;
                const absorbed = reverse ? a.target_node_name : a.source_name;
                return (
                  <div key={a.id} className="border-b border-[var(--card-hairline)] px-2.5 py-3 last:border-0">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 truncate text-[13px] text-ink-1">
                        <SafeText text={a.source_name} />
                      </span>
                      <span className="flex-none text-ink-3">→</span>
                      <span className="min-w-0 truncate text-[13px] text-ink-1">
                        <SafeText text={a.target_node_name ?? ""} />
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 font-mono text-[10px] text-ink-3">
                      <span>conf {a.confidence.toFixed(2)}</span>
                      <span>{a.occurrences}×</span>
                    </div>
                    {isPending && (
                      <div className="mt-2.5">
                        {confirmId === a.id ? (
                          <div className="flex flex-col gap-2.5">
                            <span className="font-mono text-[11px] leading-relaxed text-ink-1">
                              <span className="text-ink-3">Survives:</span> <SafeText text={survivor ?? ""} /> · <span className="text-ink-3">absorbed:</span> <SafeText text={absorbed ?? ""} />
                            </span>
                            <div className="flex flex-wrap gap-2">
                              <Chip active={reverse} onClick={() => setReverse((r) => !r)}>
                                ⇄ invert
                              </Chip>
                              <Button variant="primary" onClick={() => onReview(a.id, "approved", true, reverse)} disabled={acting} className="px-3.5 py-2 text-[12px]">
                                Confirm merge
                              </Button>
                              <Button variant="default" onClick={() => { setConfirmId(null); setReverse(false); }} disabled={acting} className="px-3.5 py-2 text-[12px]">
                                Cancel
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex gap-2">
                            <Button variant="primary" onClick={() => { setReverse(false); setConfirmId(a.id); }} disabled={acting} className="px-3.5 py-2 text-[12px]">
                              Approve
                            </Button>
                            <Button variant="default" onClick={() => onReview(a.id, "rejected")} disabled={acting} className="px-3.5 py-2 text-[12px]">
                              Reject
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </GlassCard>
      </div>
    </StateWrap>
  );
}

// ── Dictionary tab ────────────────────────────────────────────────────────────
function DictionaryTab({ isAdmin }: { isAdmin: boolean }) {
  const dict = useEntityDictionary();
  const stop = useStopEntities();
  const create = useCreateEntity();
  const update = useUpdateEntity();
  const del = useDeleteEntity();
  const reload = useReloadDictionary();
  const createStop = useCreateStopEntity();
  const delStop = useDeleteStopEntity();

  const [q, setQ] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [notes, setNotes] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [stopName, setStopName] = useState("");

  const entries: EntityEntry[] = dict.data ?? [];
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return entries.filter((e) => !needle || e.name.toLowerCase().includes(needle) || e.entity_type.toLowerCase().includes(needle));
  }, [entries, q]);
  const selected = filtered.find((e) => e.id === selectedId) ?? null;
  const busy = create.isPending || update.isPending;

  const reset = () => {
    setEditId(null);
    setName("");
    setType("");
    setNotes("");
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !type.trim() || busy) return;
    const body = { name: name.trim(), entity_type: type.trim(), notes: notes.trim() };
    const onErr = (err: unknown) => pushToast(`Save failed: ${errMsg(err)}`, { tone: "error" });
    if (editId != null) update.mutate({ id: editId, body }, { onSuccess: reset, onError: onErr });
    else create.mutate(body, { onSuccess: reset, onError: onErr });
  };
  const onDelete = (id: number) => {
    if (confirmId !== id) return setConfirmId(id);
    del.mutate(id, { onSuccess: () => setConfirmId(null), onError: () => { setConfirmId(null); pushToast("Delete failed", { tone: "error" }); } });
  };
  const addStop = () => {
    if (!stopName.trim()) return;
    createStop.mutate({ name: stopName.trim() }, { onSuccess: () => setStopName(""), onError: (e) => pushToast(`Stop failed: ${errMsg(e)}`, { tone: "error" }) });
  };

  return (
    <StateWrap query={dict} isAdmin={isAdmin}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <GlassCard className="flex max-h-[calc(100vh-250px)] flex-col p-3">
          <form onSubmit={onSubmit} className="mb-2.5 flex flex-wrap gap-2">
            <div className="min-w-[100px] flex-1">
              <TextInput value={name} onChange={setName} placeholder="Name" />
            </div>
            <div className="min-w-[80px] flex-1">
              <TextInput value={type} onChange={setType} placeholder="Type" />
            </div>
            <div className="min-w-[110px] flex-[1.3]">
              <TextInput value={notes} onChange={setNotes} placeholder="Notes" />
            </div>
            <Button variant="primary" type="submit" disabled={busy || !name.trim() || !type.trim()} className="px-4 py-2 text-[12px]">
              {editId == null ? "Add" : "Update"}
            </Button>
            {editId != null && (
              <button type="button" onClick={reset} className="flex-none rounded-btn px-3 py-2 font-mono text-[11px] text-ink-2" style={CELL}>
                Cancel
              </button>
            )}
          </form>
          <div className="mb-2.5 flex items-center gap-2">
            <div className="flex-1">
              <TextInput value={q} onChange={setQ} placeholder="Search dictionary…" />
            </div>
            <Button variant="default" onClick={() => reload.mutate()} loading={reload.isPending} className="px-3 py-2 text-[11px]">
              Reload
            </Button>
          </div>
          <div role="listbox" className="min-h-0 flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="grid place-items-center py-10 font-mono text-[12px] text-ink-3">No dictionary entries</div>
            ) : (
              filtered.map((en) => (
                <div key={en.id} className="flex items-center gap-2 border-b border-[var(--card-hairline)] px-2.5 py-2.5 last:border-0" style={selectedId === en.id ? { background: "color-mix(in srgb, var(--sec-ontology) 12%, transparent)" } : undefined}>
                  <button type="button" onClick={() => setSelectedId(en.id)} className="min-w-0 flex-1 truncate text-left text-[12.5px] text-ink-1">
                    <SafeText text={en.name} />
                  </button>
                  <span className="flex-none font-mono text-[9.5px] text-ink-3">{en.entity_type}</span>
                  <button type="button" onClick={() => { setEditId(en.id); setName(en.name); setType(en.entity_type); setNotes(en.notes ?? ""); }} className="flex-none rounded-sm px-2 py-1 font-mono text-[10.5px] text-ink-2" style={CELL}>
                    Edit
                  </button>
                  <SmallDanger onClick={() => onDelete(en.id)} disabled={del.isPending}>
                    {confirmId === en.id ? "Confirm?" : "Delete"}
                  </SmallDanger>
                </div>
              ))
            )}
          </div>
          <div className="mt-3 border-t pt-2.5" style={{ borderColor: "var(--card-hairline)" }}>
            <div className="mb-1.5 font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">Stop entities · {stop.data?.length ?? 0}</div>
            <div className="mb-2 flex items-center gap-2">
              <div className="flex-1">
                <TextInput value={stopName} onChange={setStopName} placeholder="Add stop entity…" onEnter={addStop} />
              </div>
              <Button variant="default" onClick={addStop} loading={createStop.isPending} disabled={!stopName.trim()} className="px-3 py-2 text-[11px]">
                Add
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(stop.data ?? []).map((s) => (
                <span key={s.stop_id ?? s.id ?? s.name} className="flex items-center gap-1.5 rounded-sm px-2 py-1 font-mono text-[10.5px] text-ink-1" style={CELL}>
                  <SafeText text={s.name} />
                  <button type="button" onClick={() => delStop.mutate((s.stop_id ?? s.id) as number)} disabled={delStop.isPending || (s.stop_id ?? s.id) == null} className="text-ink-3 hover:text-ink-1 disabled:opacity-40">
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
        </GlassCard>

        <GlassCard className="flex max-h-[calc(100vh-250px)] flex-col p-[18px]">
          {selected ? <EntityDetail key={selected.id} entity={{ name: selected.name, type: selected.entity_type }} /> : <div className="grid h-full place-items-center px-6 text-center font-mono text-[12px] text-ink-3">Select a dictionary entry to merge from here.</div>}
        </GlassCard>
      </div>
    </StateWrap>
  );
}

// ── Ontology Console ──────────────────────────────────────────────────────────
export function OntologyView() {
  const me = useMe();
  const isAdmin = Boolean(me.data?.is_super || me.data?.is_ceo);
  const [tab, setTab] = useState<"entities" | "predicates" | "aliases" | "dictionary">("entities");

  return (
    <>
      <div className="mb-[18px] mt-1.5 flex items-end justify-between gap-4 px-0.5">
        <div>
          <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Ontology Console</h1>
          <p className="mt-1.5 text-[12.5px] text-ink-3">Curate the entities, predicates, and aliases behind the graph.</p>
        </div>
        <div role="tablist" className="flex gap-0.5 rounded-md p-0.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
          {(["entities", "predicates", "aliases", "dictionary"] as const).map((tb) => (
            <button key={tb} type="button" role="tab" aria-selected={tab === tb} onClick={() => setTab(tb)} className={`rounded-[7px] px-3 py-1.5 font-body text-[12.5px] capitalize ${tab === tb ? "text-ink-1" : "text-ink-3"}`} style={tab === tb ? { background: "var(--card-bg)", boxShadow: "0 1px 2px rgba(0,0,0,0.15)" } : undefined}>
              {tb}
            </button>
          ))}
        </div>
      </div>

      {tab === "entities" ? <EntitiesTab isAdmin={isAdmin} /> : tab === "predicates" ? <PredicatesTab isAdmin={isAdmin} /> : tab === "aliases" ? <AliasesTab isAdmin={isAdmin} /> : <DictionaryTab isAdmin={isAdmin} />}
    </>
  );
}
