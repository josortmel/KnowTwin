import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, put, del } from "../lib/api";

export interface Document {
  id: string;
  filename: string;
  doc_type: string;
  status: string;
  trust_hint?: string;
  created_at: string;
}

const TERMINAL = new Set(["indexed", "failed"]);

export function useDocuments(projectId: number) {
  return useQuery<Document[]>({
    queryKey: ["documents", projectId],
    queryFn: () => get(`/documents?project_id=${projectId}`),
    enabled: projectId > 0,
    // Poll while any doc is still indexing; stop once all are terminal.
    refetchInterval: (query) => {
      const docs = query.state.data as Document[] | undefined;
      return docs?.some((d) => !TERMINAL.has(d.status)) ? 2000 : false;
    },
  });
}

// Full detail — VERIFIED (api/documents.py:43 DocumentResponse). The list item
// (useDocuments) omits visibility/trust_hint/retry_count/last_indexed; the detail
// endpoint carries them.
export interface DocumentDetail {
  id: string;
  uri: string;
  filename: string;
  doc_type: string;
  workspace_id: number;
  project_id: number;
  visibility: string;
  status: string;
  retry_count: number;
  processing_started_at: string | null;
  last_indexed: string | null;
  processing_metrics: Record<string, unknown> | null;
  base_weight: number;
  trust_hint: string | null;
  created_at: string;
}
export function useDocumentDetail(id: string) {
  return useQuery<DocumentDetail>({
    queryKey: ["document", id],
    queryFn: () => get(`/documents/${id}`),
    enabled: !!id,
  });
}

// Chunks preview — VERIFIED (api/documents.py:357). Params: start (offset), limit
// (default 50, max 200). Response has total_chunks + truncated.
export interface DocChunk {
  chunk_index: number;
  content: string;
  section_path: string | null;
}
export interface ChunksResponse {
  document_id: string;
  chunks: DocChunk[];
  chunks_returned: number;
  total_chunks: number;
  truncated: boolean;
}
export function useDocumentChunks(id: string, limit = 20) {
  return useQuery<ChunksResponse>({
    queryKey: ["doc-chunks", id, limit],
    queryFn: () => get(`/documents/${id}/chunks?limit=${limit}`),
    enabled: !!id,
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, projectId, trustHint }: { file: File; projectId: number; trustHint?: string }) => {
      const bridge = window.knowtwin;
      if (!bridge) throw new Error("knowtwin bridge unavailable — run inside the Electron app");
      // Defense-in-depth (VS4): reject oversize files here, before cloning the
      // buffer across IPC. Main also enforces this limit.
      if (file.size > 100 * 1024 * 1024) throw new Error("File too large (max 100MB)");
      const bytes = await file.arrayBuffer();
      const res = await bridge.uploadDocument({
        project_id: projectId,
        trust_hint: trustHint,
        filename: file.name,
        bytes,
      });
      if (!res.ok) throw new Error(res.error ?? `upload failed (${res.status ?? 0})`);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => put(`/documents/${docId}/reindex`),
    onSuccess: (_data, docId) => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["document", docId] });
      qc.invalidateQueries({ queryKey: ["doc-chunks", docId] });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => del(`/documents/${docId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });
}
