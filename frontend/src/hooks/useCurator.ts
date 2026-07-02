import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../lib/api";

// POST /projects/{pid}/curator/run is SYNCHRONOUS — it blocks and returns the
// run result directly (there is no separate curator/status endpoint to poll).
export interface CuratorResult {
  claims_created: number;
  claims_promoted: number;
  contradictions_found: number;
  gaps_found: number;
  verified_doc_id?: string;
}

export function useCuratorRun(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<CuratorResult>(`/projects/${projectId}/curator/run`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["coverage"] });
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
