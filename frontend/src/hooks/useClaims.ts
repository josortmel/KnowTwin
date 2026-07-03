import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put, del } from "../lib/api";

export interface Claim {
  id: string;
  subject_entity: string;
  predicate: string;
  object_entity?: string | null;
  object_value?: string | null;
  evidence_text: string;
  source_type: string;
  sensitivity: string;
  corroboration_level: string;
  dispute_state: string;
  trust_tier: number;
  confidence?: number;
  criticality: number;
  created_at: string;
  updated_at?: string;
}

// GET /claims returns a page: { items, total, limit, offset } — NOT a bare
// array (Hilo-confirmed). Unwrap to items so consumers get Claim[].
interface ClaimsPage {
  items: Claim[];
  total: number;
  limit: number;
  offset: number;
}

export function useClaims(projectId: number) {
  return useQuery<Claim[]>({
    queryKey: ["claims", projectId],
    queryFn: async () => {
      const page = await get<ClaimsPage>(`/claims?project_id=${projectId}`);
      return page.items;
    },
    enabled: projectId > 0,
  });
}

// Resolved disputes for the Decisions History tab. /claims dispute_state is a
// single-value exact filter (api/claims.py:399), so fetch both resolved states
// and merge, newest-updated first.
export function useResolvedClaims(projectId: number) {
  return useQuery<Claim[]>({
    queryKey: ["claims", "resolved", projectId],
    queryFn: async () => {
      const [forr, against] = await Promise.all([
        get<ClaimsPage>(`/claims?project_id=${projectId}&dispute_state=resolved_in_favor&limit=100`),
        get<ClaimsPage>(`/claims?project_id=${projectId}&dispute_state=resolved_against&limit=100`),
      ]);
      return [...forr.items, ...against.items].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
    },
    enabled: projectId > 0,
  });
}

// Project-scoped claim total (the page `total`, cheap via limit=1). Keyed under
// ["claims", ...] so the existing claim-mutation invalidations refresh it.
export function useClaimCount(projectId: number) {
  return useQuery<number>({
    queryKey: ["claims", "count", projectId],
    queryFn: async () => (await get<ClaimsPage>(`/claims?project_id=${projectId}&limit=1`)).total,
    enabled: projectId > 0,
  });
}

// Browse with server-side filters — VERIFIED (api/claims.py:362) the endpoint
// accepts corroboration_level, dispute_state, subject_entity, limit. source_type /
// sensitivity are NOT server params → the Explorer filters those client-side.
export interface ClaimFilters {
  corroboration_level?: string;
  dispute_state?: string;
  subject_entity?: string;
  limit?: number;
}
export function useClaimsFiltered(projectId: number, f: ClaimFilters) {
  return useQuery<Claim[]>({
    queryKey: ["claims-filtered", projectId, f],
    queryFn: async () => {
      const p = new URLSearchParams({ project_id: String(projectId) });
      if (f.corroboration_level) p.set("corroboration_level", f.corroboration_level);
      if (f.dispute_state) p.set("dispute_state", f.dispute_state);
      if (f.subject_entity) p.set("subject_entity", f.subject_entity);
      p.set("limit", String(f.limit ?? 50));
      const page = await get<ClaimsPage>(`/claims?${p.toString()}`);
      return page.items;
    },
    enabled: projectId > 0,
  });
}

export function usePromoteClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, newLevel, force }: { claimId: string; newLevel: string; force?: boolean }) =>
      put(`/claims/${claimId}/promote`, { new_level: newLevel, ...(force ? { force: true } : {}) }),
    onMutate: async ({ claimId, newLevel }) => {
      await qc.cancelQueries({ queryKey: ["claims"] });
      await qc.cancelQueries({ queryKey: ["claims-filtered"] });
      const prev = qc.getQueriesData<Claim[]>({ queryKey: ["claims"] });
      const prevFiltered = qc.getQueriesData<Claim[]>({ queryKey: ["claims-filtered"] });
      const updater = (old: Claim[] | undefined) =>
        old?.map((c) => (c.id === claimId ? { ...c, corroboration_level: newLevel } : c));
      qc.setQueriesData<Claim[]>({ queryKey: ["claims"] }, updater);
      qc.setQueriesData<Claim[]>({ queryKey: ["claims-filtered"] }, updater);
      return { prev, prevFiltered };
    },
    onError: (_e, _v, ctx) => {
      ctx?.prev?.forEach(([key, data]) => qc.setQueryData(key, data));
      ctx?.prevFiltered?.forEach(([key, data]) => qc.setQueryData(key, data));
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["claims-filtered"] });
      qc.invalidateQueries({ queryKey: ["graph-totals"] });
      qc.invalidateQueries({ queryKey: ["knowledge-stats"] });
    },
  });
}

export function useUpdateClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, body }: { claimId: string; body: Record<string, unknown> }) =>
      put(`/claims/${claimId}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["claims-filtered"] });
      qc.invalidateQueries({ queryKey: ["coverage"] });
    },
  });
}

export function useDeleteClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (claimId: string) => del(`/claims/${claimId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["claims-filtered"] });
    },
  });
}

// Reopen a resolved dispute (History → Reverse). Sets dispute_state back to
// "disputed" so it returns to the Decisions dispute queue.
export function useReverseDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (claimId: string) => put(`/claims/${claimId}`, { dispute_state: "disputed" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["inbox-details"] });
      qc.invalidateQueries({ queryKey: ["attention-summary"] });
    },
  });
}
