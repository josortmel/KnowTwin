import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";
import type { Claim } from "./useClaims";

// GET /graph/all — VERIFIED: { nodes:[{id,name,type,degree}], edges:[...],
// node_count, edge_count }. In the demo edge_count is 0 (no triples yet), so the
// viewport renders a node cloud until relations exist.
export interface GraphNode {
  id: number | string;
  name: string;
  type?: string | null;
  degree: number;
}
export interface GraphLink {
  source: number | string;
  target: number | string;
  predicate: string;
}
interface GraphAll {
  nodes: GraphNode[];
  edges: GraphLink[];
  node_count: number;
  edge_count: number;
}
export function useGraphAll(enabled = true) {
  return useQuery<GraphAll>({
    queryKey: ["graph-all"],
    queryFn: () => get("/graph/all"),
    enabled,
  });
}

// GET /graph/subgraph?center=&depth= — VERIFIED (api/graph.py:791). Normal:
// { center, depth, nodes, edges }. When capped: also { truncated, total_nodes,
// shown_nodes }. depth is backend-capped at 2.
export interface SubgraphResponse {
  center: string;
  depth: number;
  nodes: GraphNode[];
  edges: GraphLink[];
  truncated?: boolean;
  total_nodes?: number;
  shown_nodes?: number;
}
export function useGraphSubgraph(center: string, depth: number, enabled: boolean) {
  return useQuery<SubgraphResponse>({
    queryKey: ["graph-subgraph", center, depth],
    queryFn: () => get(`/graph/subgraph?center=${encodeURIComponent(center)}&depth=${depth}`),
    enabled: enabled && !!center,
  });
}

// GET /graph/search?q= — VERIFIED: { query, matches:[{id,name,similarity}] }.
export interface GraphMatch {
  id: number | string;
  name: string;
  similarity: number;
}
interface GraphSearchResp {
  query: string;
  matches: GraphMatch[];
}
export function useGraphSearch(q: string) {
  return useQuery<GraphMatch[]>({
    queryKey: ["graph-search", q],
    queryFn: async () => (await get<GraphSearchResp>(`/graph/search?q=${encodeURIComponent(q)}&limit=10`)).matches,
    enabled: q.trim().length > 0,
  });
}

// Node inspection: claims whose subject is the clicked entity.
// GET /claims?project_id=&subject_entity= — VERIFIED param `subject_entity`.
interface ClaimsPage {
  items: Claim[];
  total: number;
}
export function useEntityClaims(projectId: number, entity: string | null) {
  return useQuery<Claim[]>({
    queryKey: ["entity-claims", projectId, entity],
    queryFn: async () =>
      (await get<ClaimsPage>(`/claims?project_id=${projectId}&subject_entity=${encodeURIComponent(entity as string)}&limit=50`)).items,
    enabled: projectId > 0 && !!entity,
  });
}
