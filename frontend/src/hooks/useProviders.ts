import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, del } from "../lib/api";

// VERIFIED against api/providers.py. Plaintext keys never leave the server; the
// list masks each key as api_key_masked ("abc****...last4"). ProviderCreate uses
// extra="forbid" — only {provider, api_key, model_default?, display_name?} are
// accepted (no base_url field exists on the backend model).
export interface Provider {
  id: number;
  provider: string;
  api_key_masked: string;
  model_default?: string | null;
  display_name?: string | null;
  created_at: string;
}

interface Page<T> {
  items: T[];
  total: number;
}

export function useProviders() {
  return useQuery<Provider[]>({
    queryKey: ["providers"],
    queryFn: async () => {
      const r = await get<Provider[] | Page<Provider>>("/api/v1/providers");
      return Array.isArray(r) ? r : r.items ?? [];
    },
  });
}

export interface ProviderCreate {
  provider: string;
  api_key: string;
  model_default?: string;
  display_name?: string;
}

export function useCreateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProviderCreate) => post("/api/v1/providers", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  });
}

export function useDeleteProvider() {
  const qc = useQueryClient();
  return useMutation({
    // 409 if the provider is still referenced by a cell config (backend guard).
    mutationFn: (providerId: number) => del(`/api/v1/providers/${providerId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  });
}

interface ModelsResponse {
  provider: string;
  models: string[];
}

// GET /api/v1/providers/{provider}/models → { provider, models[] }. The catalog
// is hardcoded server-side per provider (deepseek/openai/anthropic).
export function useProviderModels(provider: string | null) {
  return useQuery<string[]>({
    queryKey: ["provider-models", provider],
    queryFn: async () => (await get<ModelsResponse>(`/api/v1/providers/${encodeURIComponent(provider as string)}/models`)).models ?? [],
    enabled: !!provider,
  });
}
