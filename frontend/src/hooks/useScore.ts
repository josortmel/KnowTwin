import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";

export interface Me {
  user_id: number;
  name: string;
  email?: string;
  is_super?: boolean;
  is_ceo?: boolean;
}

export function useMe() {
  return useQuery<Me>({
    queryKey: ["me"],
    queryFn: () => get<Me>("/auth/me"),
    staleTime: 5 * 60_000,
  });
}

export interface ScoreComponents {
  coverage_contrib: number;
  contradiction_yield: number;
  quality: number;
  gaming_penalty: number;
}

export interface Score {
  employee_id: number;
  score: number;
  components: ScoreComponents;
  claim_count: number;
}

// Employees see only their OWN score (server-enforced). eid is the current user.
export function useScore(projectId: number, employeeId: number | null | undefined) {
  return useQuery<Score>({
    queryKey: ["score", projectId, employeeId],
    queryFn: () => get<Score>(`/projects/${projectId}/employees/${employeeId}/score`),
    enabled: projectId > 0 && !!employeeId,
    retry: false,
  });
}
