import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put } from "../lib/api";

interface SettingsResponse {
  project_id: number;
  config: Record<string, unknown>;
}

export function useSettings(projectId: number) {
  return useQuery<SettingsResponse>({
    queryKey: ["settings", projectId],
    queryFn: () => get(`/projects/${projectId}/settings`),
    enabled: projectId > 0,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, config }: { projectId: number; config: Record<string, unknown> }) =>
      put(`/projects/${projectId}/settings`, config),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}
