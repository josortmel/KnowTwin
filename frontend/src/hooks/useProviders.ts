import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../lib/api";

interface Provider {
  provider: string;
  has_key: boolean;
}

interface Page<T> {
  items: T[];
}

export function useProviders() {
  return useQuery<Provider[]>({
    queryKey: ["providers"],
    // GET /api/v1/providers returns a paginated {items,total}, not an array.
    queryFn: async () => {
      const r = await get<Provider[] | Page<Provider>>("/api/v1/providers");
      return Array.isArray(r) ? r : r.items ?? [];
    },
  });
}

export function useSetProviderKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, apiKey }: { provider: string; apiKey: string }) =>
      post("/api/v1/providers", { provider, api_key: apiKey }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  });
}
