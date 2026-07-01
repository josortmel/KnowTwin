import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put, del } from "../lib/api";
import { getApiKey } from "../lib/auth";

interface Document {
  id: string;
  filename: string;
  doc_type: string;
  status: string;
  trust_hint?: string;
  created_at: string;
}

export function useDocuments(projectId: number) {
  return useQuery<Document[]>({
    queryKey: ["documents", projectId],
    queryFn: () => get(`/documents?project_id=${projectId}`),
    enabled: projectId > 0,
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, projectId, trustHint }: { file: File; projectId: number; trustHint?: string }) => {
      const form = new FormData();
      form.append("file", file);
      const params = new URLSearchParams({ project_id: String(projectId) });
      if (trustHint) params.set("trust_hint", trustHint);
      const key = getApiKey();
      const res = await fetch(`http://localhost:8090/documents/upload?${params}`, {
        method: "POST",
        headers: key ? { Authorization: `Bearer ${key}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => put(`/documents/${docId}/reindex`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => del(`/documents/${docId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}
