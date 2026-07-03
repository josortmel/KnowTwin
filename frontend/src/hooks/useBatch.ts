import { useMutation, useQueryClient } from "@tanstack/react-query";
import { put } from "../lib/api";
import type { Claim } from "./useClaims";

// PUT /claims/batch — ids: uuid[] (1..200), action, optional value (for
// set_sensitivity). Response has no schema in openapi; the server returns a
// partial-failure summary, so we type it defensively.
export type BatchAction = "approve" | "reject" | "set_sensitivity";

export interface BatchFailure {
  id: string;
  error: string;
}

export interface BatchResult {
  // Server returns arrays: succeeded = ids that applied, failed = per-id errors.
  succeeded?: string[];
  failed?: BatchFailure[];
}

const APPROVE_NEXT: Record<string, string> = {
  draft: "single_source",
  single_source: "corroborated",
  corroborated: "corroborated_by_employee",
  corroborated_by_employee: "validated",
};

export function useBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, action, value }: { ids: string[]; action: BatchAction; value?: string }) =>
      put<BatchResult>("/claims/batch", { ids, action, ...(value != null ? { value } : {}) }),
    onMutate: async ({ ids, action }) => {
      await qc.cancelQueries({ queryKey: ["claims"] });
      await qc.cancelQueries({ queryKey: ["claims-filtered"] });
      const prev = qc.getQueriesData<Claim[]>({ queryKey: ["claims"] });
      const prevFiltered = qc.getQueriesData<Claim[]>({ queryKey: ["claims-filtered"] });
      if (action === "approve" || action === "reject") {
        const idSet = new Set(ids);
        const updater = (old: Claim[] | undefined) =>
          old?.map((c) => {
            if (!idSet.has(c.id)) return c;
            const level = action === "reject" ? "rejected" : (APPROVE_NEXT[c.corroboration_level] ?? c.corroboration_level);
            return { ...c, corroboration_level: level };
          });
        qc.setQueriesData<Claim[]>({ queryKey: ["claims"] }, updater);
        qc.setQueriesData<Claim[]>({ queryKey: ["claims-filtered"] }, updater);
      }
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
