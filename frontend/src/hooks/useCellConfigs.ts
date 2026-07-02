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

interface Page<T> {
  items: T[];
}

export function useCellConfigs() {
  return useQuery<CellConfig[]>({
    queryKey: ["cellConfigs"],
    // GET /api/v1/cells/configs returns a paginated {items,total}, not an array.
    queryFn: async () => {
      const r = await get<CellConfig[] | Page<CellConfig>>("/api/v1/cells/configs");
      return Array.isArray(r) ? r : r.items ?? [];
    },
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
