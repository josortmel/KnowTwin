import { useQuery } from "@tanstack/react-query";
import type { ApiStatus } from "../components/StatusPill";

interface Health {
  status?: string;
}

// Polls GET /health through the bridge (~20s) and maps it to a StatusPill state.
// The API confirmed `{ "status": "ok" }` when healthy (Hilo).
export function useHealth(): ApiStatus {
  const q = useQuery<ApiStatus>({
    queryKey: ["health"],
    queryFn: async () => {
      const bridge = window.knowtwin;
      if (!bridge) return "unknown";
      const res = await bridge.fetch<Health>("/health");
      if (!res.ok) return "offline";
      return res.data?.status === "ok" ? "online" : "degraded";
    },
    refetchInterval: 20_000,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 15_000,
  });
  if (q.isError) return "offline";
  return q.data ?? "unknown";
}
