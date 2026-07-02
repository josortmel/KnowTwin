import { useMutation, useQuery } from '@tanstack/react-query';
import { post, get } from '../lib/api';

export interface DocStrengthBreakdown {
  source_count: number;
  freshness_score: number;
  trust_tier: number;
  computed_strength: number;
}

export interface TwinSource {
  claim_id: string;
  subject_entity: string;
  predicate: string;
  object_entity?: string | null;
  object_value?: string | null;
  evidence_text: string;
  source_type?: string;
  sensitivity: string;
  corroboration_level: string;
  dispute_state: string;
  criticality: number;
  score: number;
  doc_strength_breakdown?: DocStrengthBreakdown | null;
  why_resolved?: string | null;
}

export interface DisputeGroup {
  subject_entity: string;
  predicate: string;
  versions: TwinSource[];
}

export interface TwinResponse {
  answer: string;
  sources: TwinSource[];
  disputes: DisputeGroup[];
  coverage_context: Record<string, unknown> | null;
}

export interface CoverageEntity {
  entity_name: string;
  entity_type: string;
  coverage_pct: number;
  coverage_state: string;
}

export interface CoverageResponse {
  project_id: number;
  overall_coverage_pct: number;
  entity_count: number;
  entities: CoverageEntity[];
}

export function useTwinQuery() {
  return useMutation({
    mutationFn: async ({ question, project_id }: { question: string; project_id: number }) => {
      return post<TwinResponse>('/twin/query', { question, project_id });
    },
  });
}

// Search as a cached query (Explorer). POST /twin/query, enabled only with a
// non-empty question — the caller debounces the input.
export function useTwinSearch(question: string, projectId: number) {
  return useQuery<TwinResponse>({
    queryKey: ['twin-search', projectId, question],
    queryFn: () => post<TwinResponse>('/twin/query', { question, project_id: projectId }),
    enabled: projectId > 0 && question.trim().length > 0,
  });
}

export function useTwinCoverage(projectId: number) {
  return useQuery({
    queryKey: ['twin-coverage', projectId],
    queryFn: async () => {
      return get<CoverageResponse>(`/twin/coverage?project_id=${projectId}`);
    },
    enabled: projectId > 0,
  });
}
