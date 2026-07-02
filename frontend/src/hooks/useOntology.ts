import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "../lib/api";

// All /admin/* endpoints are super/CEO-gated: mutations may 403 for non-admins.
// The renderer surfaces those errors as toasts (frontend is not a security boundary).

// ── Entity dictionary ─────────────────────────────────────────────────────────
// GET /admin/entity-dictionary → EntityEntry[] (VERIFIED shape).
export interface EntityEntry {
  id: number;
  name: string;
  name_normalized: string;
  entity_type: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}
export function useEntityDictionary() {
  return useQuery<EntityEntry[]>({
    queryKey: ["entity-dictionary"],
    queryFn: () => get("/admin/entity-dictionary"),
  });
}

function invalidateEntities(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["entity-dictionary"] });
  qc.invalidateQueries({ queryKey: ["graph-vocabulary"] });
  qc.invalidateQueries({ queryKey: ["coverage"] });
}

export function useCreateEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; entity_type: string; notes?: string }) => post("/admin/entity-dictionary", body),
    onSuccess: () => invalidateEntities(qc),
  });
}

export function useUpdateEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; entity_type?: string; notes?: string } }) =>
      put(`/admin/entity-dictionary/${id}`, body),
    onSuccess: () => invalidateEntities(qc),
  });
}

export function useDeleteEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => del(`/admin/entity-dictionary/${id}`),
    onSuccess: () => invalidateEntities(qc),
  });
}

export function useReloadDictionary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post("/admin/entity-dictionary/reload", {}),
    onSuccess: () => invalidateEntities(qc),
  });
}

// ── Alias candidates ──────────────────────────────────────────────────────────
// GET /admin/alias-candidates?status=&limit= — VERIFIED (api/admin.py:822)
// list[AliasCandidateRow]. status ∈ pending|approved|rejected|archived.
export interface AliasItem {
  id: number;
  source_name: string;
  target_node_id: number;
  target_node_name: string | null;
  confidence: number;
  occurrences: number;
  status: string;
}
export function useAliasCandidates(status = "pending", limit = 50) {
  return useQuery<AliasItem[]>({
    queryKey: ["alias-candidates", status, limit],
    queryFn: () => get(`/admin/alias-candidates?status=${status}&limit=${limit}`),
  });
}

// POST /admin/alias-candidates/scan — VERIFIED. dry_run=true = preview (no writes).
export interface AliasScanCandidate {
  source_name: string;
  target_node_id: number;
  target_node_name?: string;
  confidence: number;
}
export interface AliasScanResponse {
  found: number;
  inserted: number;
  updated: number;
  total_pending: number;
  candidates: AliasScanCandidate[];
}
export function useScanAliases() {
  const qc = useQueryClient();
  return useMutation<AliasScanResponse, Error, { threshold: number; max_per_name?: number; name_filter?: string; dry_run?: boolean }>({
    mutationFn: (body) => post("/admin/alias-candidates/scan", { max_per_name: 5, dry_run: false, ...body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alias-candidates"] }),
  });
}

// PUT /admin/alias-candidates/{id} — VERIFIED body { status, merge, reverse }.
// reverse=true merges target INTO source (source survives) instead of the default.
export function useReviewAlias() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, merge, reverse }: { id: number; status: string; merge?: boolean; reverse?: boolean }) =>
      put(`/admin/alias-candidates/${id}`, { status, merge: !!merge, ...(reverse != null ? { reverse } : {}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alias-candidates"] });
      invalidateEntities(qc);
    },
  });
}

export function useUndoMerge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceNodeId: number) => post("/admin/undo-merge", { source_node_id: sourceNodeId }),
    onSuccess: () => invalidateEntities(qc),
  });
}

// POST /admin/merge-entities — VERIFIED (api/admin.py:1031) body
// { source_node_id, target_node_id, keep_as_alias }. IDs are GRAPH NODE IDs. Admin.
export function useMergeEntities() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ source_node_id, target_node_id, keep_as_alias }: { source_node_id: number; target_node_id: number; keep_as_alias: boolean }) =>
      post("/admin/merge-entities", { source_node_id, target_node_id, keep_as_alias }),
    onSuccess: () => {
      invalidateEntities(qc);
      qc.invalidateQueries({ queryKey: ["graph-all"] });
      qc.invalidateQueries({ queryKey: ["graph-subgraph"] });
    },
  });
}

// ── Stop entities ─────────────────────────────────────────────────────────────
// GET /admin/stop-entities → [] in demo. DELETE by {stop_id}.
export interface StopEntity {
  id?: number;
  stop_id?: number;
  name: string;
  reason?: string | null;
}
export function useStopEntities() {
  return useQuery<StopEntity[]>({
    queryKey: ["stop-entities"],
    queryFn: () => get("/admin/stop-entities"),
  });
}

export function useCreateStopEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; reason?: string }) => post("/admin/stop-entities", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stop-entities"] }),
  });
}

export function useDeleteStopEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stopId: number) => del(`/admin/stop-entities/${stopId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stop-entities"] }),
  });
}

// ── Predicates / vocabulary ───────────────────────────────────────────────────
// GET /admin/graph-vocabulary → { entities, predicates, entity_count, predicate_count } (VERIFIED).
export interface Predicate {
  name: string;
  description: string;
  state: string;
  cluster: string;
}
interface GraphVocabulary {
  entities: { name: string; type: string }[];
  predicates: Predicate[];
  entity_count: number;
  predicate_count: number;
}
export function useGraphVocabulary() {
  return useQuery<GraphVocabulary>({
    queryKey: ["graph-vocabulary"],
    queryFn: () => get("/admin/graph-vocabulary"),
  });
}

function invalidateVocab(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["graph-vocabulary"] });
  qc.invalidateQueries({ queryKey: ["predicate-aliases"] });
}

export function useCreatePredicate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string; cluster?: string; state?: string }) => post("/admin/predicates", body),
    onSuccess: () => invalidateVocab(qc),
  });
}

export function useUpdatePredicate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: { description?: string; cluster?: string; state?: string } }) =>
      put(`/admin/predicates/${encodeURIComponent(name)}`, body),
    onSuccess: () => invalidateVocab(qc),
  });
}

export function useDeletePredicate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => del(`/admin/predicates/${encodeURIComponent(name)}`),
    onSuccess: () => invalidateVocab(qc),
  });
}

// GET /graph/predicates/aliases → { aliases: [] } in demo.
interface PredicateAliasesResp {
  aliases: { alias: string; canonical: string }[];
}
export function usePredicateAliases() {
  return useQuery<PredicateAliasesResp["aliases"]>({
    queryKey: ["predicate-aliases"],
    queryFn: async () => (await get<PredicateAliasesResp>("/graph/predicates/aliases")).aliases ?? [],
  });
}
