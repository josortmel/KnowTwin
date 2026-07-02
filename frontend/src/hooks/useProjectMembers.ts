import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";

export interface ProjectMember {
  user_id: number;
  name: string;
  role: string;
}

// GET /projects/{pid}/members (curator/admin authz) — feeds the resolver dropdown.
export function useProjectMembers(projectId: number) {
  return useQuery<ProjectMember[]>({
    queryKey: ["members", projectId],
    queryFn: () => get<ProjectMember[]>(`/projects/${projectId}/members`),
    enabled: projectId > 0,
  });
}
