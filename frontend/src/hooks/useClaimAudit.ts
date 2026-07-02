import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";

// Real fields (Hilo, verified): `timestamp` (not created_at) and `details` is a
// JSON STRING, not an object.
export interface AuditEntry {
  id: number;
  user_id: number | null;
  action: string;
  details?: string | null;
  timestamp: string;
}

export function useClaimAudit(claimId: string | null) {
  return useQuery<AuditEntry[]>({
    queryKey: ["audit", claimId],
    queryFn: () => get<AuditEntry[]>(`/claims/${claimId}/audit`),
    enabled: !!claimId,
  });
}
