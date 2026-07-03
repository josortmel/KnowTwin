import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../lib/api";

const WORKSPACE_ID = 1;

// GET /workspaces/{id}/projects — VERIFIED (api/projects.py:259, ProjectResponse).
// Returns { items:[ProjectResponse], total }. The list now carries employee_name
// + department (Hilo update).
export interface WorkspaceProject {
  id: number;
  workspace_id: number;
  name: string;
  is_common: boolean;
  department?: string | null;
  exit_date?: string | null;
  disposition?: string | null;
  employee_name?: string | null;
  employee_id?: number | null;
  created_at: string;
}
interface ProjectListResponse {
  items: WorkspaceProject[];
  total: number;
}
export function useWorkspaceProjects() {
  return useQuery<WorkspaceProject[]>({
    queryKey: ["projects", WORKSPACE_ID],
    queryFn: async () => (await get<ProjectListResponse>(`/workspaces/${WORKSPACE_ID}/projects`)).items ?? [],
  });
}

// GET /projects/{id}/status — VERIFIED (api/projects.py:402).
export type ProcessStage = "setup" | "documents" | "curation" | "interviews" | "complete";
export interface ProjectStatus {
  project_id: number;
  project_name: string;
  stage: ProcessStage;
  documents: number;
  claims: number;
  sessions: number;
  completed_sessions: number;
  coverage_pct: number;
  open_disputes?: number;
}
export function useProjectStatus(projectId: number, enabled = true) {
  return useQuery<ProjectStatus>({
    queryKey: ["project-status", projectId],
    queryFn: () => get(`/projects/${projectId}/status`),
    enabled: enabled && projectId > 0,
  });
}

// GET /projects/{id}/next-steps — VERIFIED (api/projects.py:452). Returns
// { project_id, steps:[{action, label}], coverage_pct }. NOTE: steps carry
// `action` + `label` only — no separate priority/gaps fields (gap names are
// embedded in the label string).
export interface NextStep {
  action: string;
  label: string;
}
interface NextStepsResponse {
  project_id: number;
  steps: NextStep[];
  coverage_pct: number;
}
export function useProjectNextSteps(projectId: number, enabled = true) {
  return useQuery<NextStep[]>({
    queryKey: ["project-next-steps", projectId],
    queryFn: async () => (await get<NextStepsResponse>(`/projects/${projectId}/next-steps`)).steps ?? [],
    enabled: enabled && projectId > 0,
  });
}

// POST /projects — VERIFIED (api/projects.py:82, OffboardingCreate). Persisted:
// { name, employee_name?, role?, department?, exit_date?, accounts?, disposition? }.
// exit_date is a YYYY-MM-DD string. The model does NOT set extra="forbid", so
// reporting_manager/replacement_name/priority are accepted but silently dropped
// (not persisted yet — pending backend columns).
export interface CreateProcessInput {
  employeeName: string;
  role: string;
  department: string;
  exitDate: string;
  disposition: string;
  reportingManager: string;
  replacementName: string;
  priority: string;
  knowledgeAreas: string[];
}
export function useCreateProcess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateProcessInput) =>
      post<WorkspaceProject>("/projects", {
        name: `${input.employeeName} Offboarding`,
        employee_name: input.employeeName,
        role: input.role || undefined,
        department: input.department || undefined,
        exit_date: input.exitDate || undefined,
        disposition: input.disposition || undefined,
        accounts: input.knowledgeAreas.length ? input.knowledgeAreas : undefined,
        // Not yet persisted by the backend model (accepted + ignored):
        reporting_manager: input.reportingManager || undefined,
        replacement_name: input.replacementName || undefined,
        priority: input.priority || undefined,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}
