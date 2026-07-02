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

export function useBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, action, value }: { ids: string[]; action: BatchAction; value?: string }) =>
      put<BatchResult>("/claims/batch", { ids, action, ...(value != null ? { value } : {}) }),
    // Optimistic: reflect approve/reject on the affected rows immediately;
    // roll back on any error (incl. 409/403), then revalidate.
    onMutate: async ({ ids, action }) => {
      await qc.cancelQueries({ queryKey: ["claims"] });
      const prev = qc.getQueriesData<Claim[]>({ queryKey: ["claims"] });
      if (action === "approve" || action === "reject") {
        const level = action === "approve" ? "validated" : "rejected";
        const idSet = new Set(ids);
        qc.setQueriesData<Claim[]>({ queryKey: ["claims"] }, (old) =>
          old?.map((c) => (idSet.has(c.id) ? { ...c, corroboration_level: level } : c)),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      ctx?.prev?.forEach(([key, data]) => qc.setQueryData(key, data));
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["claims"] }),
  });
}
