import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";

// Memory (claim) counts — VERIFIED (api/stats.py:34) GET /api/v1/stats/memories →
// { period, group_by, data:[{label,count}], total }. data[0] is the top type.
export interface MemoryTypeCount {
  label: string;
  count: number;
}
export interface MemoryStats {
  period: string;
  group_by: string;
  data: MemoryTypeCount[];
  total: number;
}
export function useMemoryStats() {
  return useQuery<MemoryStats>({
    queryKey: ["memory-stats"],
    queryFn: () => get("/api/v1/stats/memories"),
  });
}

// Graph totals — VERIFIED (api/stats.py:92) GET /api/v1/stats/graph →
// { nodes_total, triples_total, daily:[...] }.
export interface GraphTotals {
  nodes_total: number;
  triples_total: number;
}
export function useGraphTotals() {
  return useQuery<GraphTotals>({
    queryKey: ["graph-totals"],
    queryFn: () => get("/api/v1/stats/graph"),
  });
}

// System stats — VERIFIED (api/stats.py:265) GET /api/v1/stats/system →
// { embeddings:{status,...}, db:{claims_count,nodes_count,triples_count}, media }.
export interface SystemStats {
  embeddings: { status: string };
  db: { claims_count: number; nodes_count: number; triples_count: number };
}
export function useSystemStats() {
  return useQuery<SystemStats>({
    queryKey: ["system-stats"],
    queryFn: () => get("/api/v1/stats/system"),
  });
}

// Knowledge health — VERIFIED (api/stats.py:401) GET /api/v1/stats/knowledge.
// Super-only (403 for non-super → query errors → panel degrades). Called
// system-wide (no project_id) so duplicate_candidate_count is included.
export interface TopEntity {
  id: number;
  name: string;
  type: string;
  degree: number;
}
export interface KnowledgeStats {
  entity_count: number;
  merged_entity_count: number;
  alias_candidate_count: number;
  merge_count: number;
  orphan_entity_count: number;
  stale_claim_count: number;
  dormant_claim_count: number;
  duplicate_candidate_count: number;
  graph_density: number;
  top_entities_by_degree: TopEntity[];
}
export function useKnowledgeStats() {
  return useQuery<KnowledgeStats>({
    queryKey: ["knowledge-stats"],
    queryFn: () => get("/api/v1/stats/knowledge"),
  });
}

// Activity timeline — VERIFIED (api/stats.py:317) GET /api/v1/stats/timeline?period=N →
// { period_days, timeline:[{date,claims,documents,searches}] } ascending. We unwrap
// and reverse to DESC (most recent first) for the feed.
export interface TimelineDay {
  date: string;
  claims: number;
  documents: number;
  searches: number;
}
interface TimelineResp {
  period_days: number;
  timeline: TimelineDay[];
}
export function useTimeline(period = 7) {
  return useQuery<TimelineDay[]>({
    queryKey: ["timeline", period],
    queryFn: async () => {
      const r = await get<TimelineResp>(`/api/v1/stats/timeline?period=${period}`);
      return [...(r.timeline ?? [])].reverse();
    },
  });
}

// Attention inbox — VERIFIED (api/admin.py:113) GET /admin/attention-inbox/summary →
// { classes:{ <class>: count }, total }. Six KnowTwin decision classes, ordered by
// curator urgency (disputes are the #1 workflow; deletions are GDPR — can't wait).
export interface AttentionClass {
  key: string;
  label: string;
}
export const ATTENTION_CLASSES: AttentionClass[] = [
  { key: "pending_disputes", label: "Pending disputes" },
  { key: "pending_deletions", label: "Pending deletions" },
  { key: "low_trust_documents", label: "Low-trust documents" },
  { key: "stale_claims", label: "Stale claims" },
  { key: "pending_alias_candidates", label: "Alias candidates" },
  { key: "unconfirmed_relations", label: "Unconfirmed relations" },
];

export interface AttentionSummary {
  classes: Record<string, number>;
  total: number;
}
export function useAttentionSummary() {
  return useQuery<AttentionSummary>({
    queryKey: ["attention-summary"],
    queryFn: () => get("/admin/attention-inbox/summary"),
  });
}

// Employee scores — VERIFIED (api/scoring.py:150) GET /projects/{id}/scores →
// [{ employee_id, score, components, claim_count }]. Curator-only (403 → degrade).
// No name in payload; resolve via project members. Process framing (§7.6) — never
// person-ranking.
export interface EmployeeScore {
  employee_id: number;
  score: number;
  components: { coverage_contrib: number; contradiction_yield: number; quality: number; gaming_penalty: number };
  claim_count: number;
}
export function useAllScores(projectId: number) {
  return useQuery<EmployeeScore[]>({
    queryKey: ["all-scores", projectId],
    queryFn: () => get(`/projects/${projectId}/scores`),
    enabled: projectId > 0,
    retry: false,
  });
}
