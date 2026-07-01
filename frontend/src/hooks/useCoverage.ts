import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";

interface CoverageEntity {
  entity_name: string;
  entity_type: string;
  confirmed_count: number;
  expected_count: number;
  coverage_pct: number;
  coverage_state: string;
}

interface CoverageResponse {
  project_id: number;
  overall_coverage_pct: number;
  entity_count: number;
  entities: CoverageEntity[];
}

export function useCoverage(projectId: number) {
  return useQuery<CoverageResponse>({
    queryKey: ["coverage", projectId],
    queryFn: () => get(`/twin/coverage?project_id=${projectId}`),
    enabled: projectId > 0,
  });
}
