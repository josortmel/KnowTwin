import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put } from "../lib/api";

export interface DocStrengthBreakdown {
  source_count: number;
  freshness_score: number;
  trust_tier: number;
  computed_strength: number;
}

export interface DisputeSide {
  claim_id: string;
  subject_entity: string;
  predicate: string;
  object_entity?: string | null;
  object_value?: string | null;
  evidence_text: string;
  source_type: string;
  sensitivity: string;
  corroboration_level: string;
  dispute_state: string;
  criticality: number;
  doc_strength_breakdown?: DocStrengthBreakdown | null;
  resolution_note?: string | null;
  resolver_user_id?: number | null;
  resolved_by_user_id?: number | null;
}

export interface Dispute {
  claim: DisputeSide;
  // Some disputed claims have no paired counterpart yet.
  counterpart: DisputeSide | null;
}

interface DisputesResponse {
  disputes: Dispute[];
  total: number;
}

export function useDisputes(projectId: number) {
  return useQuery<Dispute[]>({
    queryKey: ["disputes", projectId],
    queryFn: async () => {
      const r = await get<DisputesResponse>(`/claims/disputes?project_id=${projectId}`);
      return r.disputes;
    },
    enabled: projectId > 0,
  });
}

export type Resolution = "in_favor" | "against";

export function useResolveDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, resolution, note }: { claimId: string; resolution: Resolution; note: string }) =>
      put(`/claims/${claimId}/resolve`, { resolution, resolution_note: note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["disputes"] });
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["coverage"] });
      // Cross-view: the Decisions Inbox list + the Dashboard/inbox counts.
      qc.invalidateQueries({ queryKey: ["inbox-details"] });
      qc.invalidateQueries({ queryKey: ["attention-summary"] });
    },
  });
}

export function useAssignResolver() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, resolverUserId }: { claimId: string; resolverUserId: number }) =>
      put(`/claims/${claimId}/assign-resolver`, { resolver_user_id: resolverUserId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["disputes"] });
      qc.invalidateQueries({ queryKey: ["inbox-details"] });
    },
  });
}

export interface DisputeDetail {
  claim: DisputeSide;
  counterpart: DisputeSide;
  why_resolved?: string | null;
}

export function useDisputeDetail(claimId: string | null) {
  return useQuery<DisputeDetail>({
    queryKey: ["dispute-detail", claimId],
    queryFn: () => get<DisputeDetail>(`/claims/${claimId}/dispute-detail`),
    enabled: !!claimId,
  });
}
