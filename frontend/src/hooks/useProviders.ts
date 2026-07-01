import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../lib/api";

interface Provider {
  provider: string;
  has_key: boolean;
}

export function useProviders() {
  return useQuery<Provider[]>({
    queryKey: ["providers"],
    queryFn: () => get("/api/v1/providers"),
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
