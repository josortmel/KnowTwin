import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "../lib/api";

// VERIFIED against api/cell_configs.py. Writes are super-only. Both create and
// update carry `provider` (the provider NAME, ^[a-z0-9_]+$) and `model` — there
// is no provider_id. Create additionally REQUIRES agent_identifier.
export interface CellConfig {
  id: number;
  agent_id: number;
  agent_identifier: string;
  cell_type: string;
  enabled: boolean;
  model: string;
  provider: string;
  level?: string | null;
  config?: Record<string, unknown>;
  prompt_template_id?: number | null;
  prompt_template_name?: string | null;
  updated_at: string;
}

interface Page<T> {
  items: T[];
  total: number;
}

export function useCellConfigs() {
  return useQuery<CellConfig[]>({
    queryKey: ["cellConfigs"],
    queryFn: async () => {
      const r = await get<CellConfig[] | Page<CellConfig>>("/api/v1/cells/configs");
      return Array.isArray(r) ? r : r.items ?? [];
    },
  });
}

export interface CellConfigCreate {
  agent_identifier: string;
  cell_type: string;
  provider: string;
  model: string;
  enabled?: boolean;
}

export function useCreateCellConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CellConfigCreate) => post("/api/v1/cells/configs", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cellConfigs"] }),
  });
}

export function useUpdateCellConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { provider?: string; model?: string; enabled?: boolean; config?: Record<string, unknown> } }) =>
      put(`/api/v1/cells/configs/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cellConfigs"] }),
  });
}

// POST /cells/configs/{id}/reset — VERIFIED (api/cell_configs.py:265). Restores
// config (model/provider/params) AND the linked prompt template to seeded
// defaults. 409 if no defaults were stored. Refreshes both configs + templates.
export function useResetCellConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => post(`/api/v1/cells/configs/${id}/reset`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cellConfigs"] });
      qc.invalidateQueries({ queryKey: ["cellTemplates"] });
    },
  });
}

// Prompt templates (behavior/system-prompt editor) — VERIFIED api/cell_templates.py.
// super-only. GET → {items}, POST/PUT extra="forbid", DELETE 409 if referenced.
export interface PromptTemplate {
  id: number;
  name: string;
  cell_type: string;
  content: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export function useCellTemplates() {
  return useQuery<PromptTemplate[]>({
    queryKey: ["cellTemplates"],
    queryFn: async () => {
      const r = await get<PromptTemplate[] | { items: PromptTemplate[] }>("/api/v1/cells/templates");
      return Array.isArray(r) ? r : r.items ?? [];
    },
  });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; cell_type: string; content: string; is_default?: boolean }) =>
      post("/api/v1/cells/templates", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cellTemplates"] }),
  });
}

export function useUpdateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; content?: string; cell_type?: string; is_default?: boolean } }) =>
      put(`/api/v1/cells/templates/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cellTemplates"] }),
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => del(`/api/v1/cells/templates/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cellTemplates"] }),
  });
}
