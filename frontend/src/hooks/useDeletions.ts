import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put } from "../lib/api";

export interface DeletionRequest {
  id: string;
  claim_id: string;
  requested_by?: number | null;
  reason?: string | null;
  status: string;
  created_at: string;
}

export function useDeletionRequests(projectId: number) {
  return useQuery<DeletionRequest[]>({
    queryKey: ["deletion-requests", projectId],
    queryFn: () => get<DeletionRequest[]>(`/claims/deletion-requests?project_id=${projectId}`),
    enabled: projectId > 0,
  });
}

// Employee requests deletion of their OWN claim (right to erasure).
export function useRequestDeletion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, reason }: { claimId: string; reason?: string }) =>
      post(`/my-claims/${claimId}/request-deletion`, reason ? { reason } : {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deletion-requests"] }),
  });
}

export type ReviewDecision = "approve" | "reject";

// Curator/admin reviews a deletion request. approve = irreversible GDPR erasure.
export function useReviewDeletion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, decision, note }: { requestId: string; decision: ReviewDecision; note?: string }) =>
      put(`/claims/deletion-requests/${requestId}/review`, { decision, ...(note ? { note } : {}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deletion-requests"] });
      qc.invalidateQueries({ queryKey: ["claims"] });
      // Cross-view: the Decisions Inbox list + Dashboard/inbox counts.
      qc.invalidateQueries({ queryKey: ["inbox-details"] });
      qc.invalidateQueries({ queryKey: ["attention-summary"] });
    },
  });
}
