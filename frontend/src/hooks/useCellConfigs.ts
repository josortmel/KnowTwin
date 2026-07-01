import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put } from "../lib/api";

interface CellConfig {
  id: number;
  agent_id: number;
  cell_type: string;
  level?: string;
  model?: string;
  provider?: string;
  enabled: boolean;
}

export function useCellConfigs() {
  return useQuery<CellConfig[]>({
    queryKey: ["cellConfigs"],
    queryFn: () => get("/api/v1/cells/configs"),
  });
}

export function useUpdateCellConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      put(`/api/v1/cells/configs/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cellConfigs"] }),
  });
}
