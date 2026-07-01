import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../lib/api";
import { getApiKey } from "../lib/auth";

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
  coverage_pct: number | null;
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
      const key = getApiKey();
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`http://localhost:8090/interviews/${sessionId}/voice`, {
        method: "POST",
        headers: key ? { Authorization: `Bearer ${key}` } : {},
        body: fd,
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      return res.json() as Promise<RespondResult>;
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
