import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../lib/api";

interface Session {
  id: string;
  project_id: number;
  employee_id: number;
  topic: string;
  status: string;
  claims_extracted?: number;
  created_at: string | null;
  completed_at: string | null;
}

interface RespondResult {
  turn: number;
  claims_created: string[];
  turn_value: number;
  converged: boolean;
  topic: string | null;
  state: string;
  // LLM-generated follow-up question for the next turn (backend: /respond).
  message?: string | null;
  coverage_pct: number | null;
}

// GET /projects/{id}/suggested-topics — VERIFIED (api/coverage.py:63). Returns
// { project_id, topics: [...] } (entity_name, not `entity`), coverage gaps ordered
// by criticality DESC then coverage ASC.
export interface SuggestedTopic {
  entity_name: string;
  entity_type: string;
  coverage_pct: number;
  coverage_state: string;
  criticality: number;
}
export function useSuggestedTopics(projectId: number) {
  return useQuery<SuggestedTopic[]>({
    queryKey: ["suggested-topics", projectId],
    queryFn: async () => (await get<{ topics: SuggestedTopic[] }>(`/projects/${projectId}/suggested-topics?limit=10`)).topics ?? [],
    enabled: projectId > 0,
  });
}

export function useSessionList(projectId: number) {
  return useQuery<Session[]>({
    queryKey: ["interviews", projectId],
    queryFn: () => get(`/interviews?project_id=${projectId}`),
    enabled: !!projectId,
  });
}

export function useCreateSession(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (topic: string) =>
      post<Session>("/interviews", { project_id: projectId, topic }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interviews", projectId] }),
  });
}

export function useStartSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      post<{ status: string; topic: string }>(`/interviews/${sessionId}/start`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interviews"] }),
  });
}

export function useRespond(sessionId: string) {
  return useMutation({
    mutationFn: (text: string) =>
      post<RespondResult>(`/interviews/${sessionId}/respond`, { text }),
  });
}

export function useUploadVoice(sessionId: string) {
  return useMutation({
    mutationFn: async (file: File) => {
      const bridge = window.knowtwin;
      if (!bridge) throw new Error("knowtwin bridge unavailable — run inside the Electron app");
      // Defense-in-depth (VS4): reject oversize files before crossing IPC.
      if (file.size > 100 * 1024 * 1024) throw new Error("File too large (max 100MB)");
      const bytes = await file.arrayBuffer();
      const res = await bridge.uploadVoice({
        session_id: sessionId,
        filename: file.name || "voice.webm",
        bytes,
      });
      if (!res.ok) throw new Error(res.error ?? `voice upload failed (${res.status ?? 0})`);
      return res.data as RespondResult;
    },
  });
}

export function useCloseSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      post<{ status: string }>(`/interviews/${sessionId}/close`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interviews"] }),
  });
}
