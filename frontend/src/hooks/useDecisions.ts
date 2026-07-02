import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put } from "../lib/api";

// Per-class inbox details — VERIFIED (api/admin.py:248) GET
// /admin/attention-inbox/details?decision_class=&limit=&offset= →
// { class, total, items, limit, offset }. Super/CEO only (403 otherwise). Item
// shape varies by class; the detail panel narrows it.
export interface InboxItem {
  id: string;
  // stale / generic
  content?: string;
  type?: string;
  staleness?: string;
  agent_identifier?: string | null;
  created_at?: string;
  // disputes
  evidence_text?: string;
  source_type?: string;
  dispute_state?: string;
  updated_at?: string;
  // deletions
  claim_id?: string;
  reason?: string;
  status?: string;
  // alias candidates
  source_name?: string;
  target_node_name?: string;
  confidence?: number;
  occurrences?: number;
}
export interface InboxDetails {
  class: string;
  total: number;
  items: InboxItem[];
  limit: number;
  offset: number;
}
export function useInboxDetails(decisionClass: string, limit: number, offset: number, enabled: boolean) {
  return useQuery<InboxDetails>({
    queryKey: ["inbox-details", decisionClass, limit, offset],
    queryFn: () => get(`/admin/attention-inbox/details?decision_class=${decisionClass}&limit=${limit}&offset=${offset}`),
    enabled,
  });
}

// PUT /memories/{id}/staleness — VERIFIED (api/memories.py:1121). Body { staleness }.
export type Staleness = "active" | "dormant" | "archived";
export function useUpdateStaleness() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, staleness }: { id: string; staleness: Staleness }) => put(`/memories/${id}/staleness`, { staleness }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inbox-details"] });
      qc.invalidateQueries({ queryKey: ["attention-summary"] });
      // Cross-view: Explorer claim list + Dashboard KnowledgeHealth stale count.
      qc.invalidateQueries({ queryKey: ["claims"] });
      qc.invalidateQueries({ queryKey: ["knowledge-stats"] });
    },
  });
}
