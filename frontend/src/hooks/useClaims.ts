import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put, del } from "../lib/api";

interface Claim {
  id: string;
  subject_entity: string;
  predicate: string;
  object_value?: string;
  evidence_text: string;
  sensitivity: string;
  corroboration_level: string;
  dispute_state: string;
  criticality: number;
  created_at: string;
}

export function useClaims(projectId: number) {
  return useQuery<Claim[]>({
    queryKey: ["claims", projectId],
    queryFn: () => get(`/claims?project_id=${projectId}`),
    enabled: projectId > 0,
  });
}

export function usePromoteClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, newLevel }: { claimId: string; newLevel: string }) =>
      put(`/claims/${claimId}/promote`, { new_level: newLevel }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["claims"] }),
  });
}

export function useUpdateClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ claimId, body }: { claimId: string; body: Record<string, unknown> }) =>
      put(`/claims/${claimId}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["coverage"] });
    },
  });
}

export function useDeleteClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (claimId: string) => del(`/claims/${claimId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["claims"] }),
  });
}
