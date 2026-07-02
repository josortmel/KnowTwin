import { get } from "../lib/api";

function csvSafe(value: unknown): string {
  let s = String(value ?? "");
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  if (s.includes(",") || s.includes('"') || s.includes("\n")) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

function downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

interface Claim {
  id: string;
  subject_entity: string;
  predicate: string;
  object_value?: string;
  evidence_text: string;
  sensitivity: string;
  corroboration_level: string;
  dispute_state: string;
  criticality: number;
}

interface CoverageEntity {
  entity_name: string;
  entity_type: string;
  coverage_pct: number;
  coverage_state: string;
}

export async function exportClaimLedger(projectId: number) {
  const claims = await get<Claim[]>(`/claims?project_id=${projectId}`);
  const header = "id,subject_entity,predicate,object_value,evidence_text,sensitivity,corroboration_level,dispute_state,criticality";
  const rows = claims.map((c) =>
    [c.id, c.subject_entity, c.predicate, c.object_value ?? "", c.evidence_text,
     c.sensitivity, c.corroboration_level, c.dispute_state, c.criticality]
      .map(csvSafe).join(",")
  );
  downloadBlob([header, ...rows].join("\n"), `claims_project_${projectId}.csv`, "text/csv");
}

export async function exportGraphDump(projectId: number) {
  const data = await get<{ entities: CoverageEntity[] }>(`/graph/entities?project_id=${projectId}`);
  const header = "entity_name,entity_type,coverage_pct,coverage_state";
  const rows = data.entities.map((e) =>
    [e.entity_name, e.entity_type, e.coverage_pct, e.coverage_state]
      .map(csvSafe).join(",")
  );
  downloadBlob([header, ...rows].join("\n"), `entities_project_${projectId}.csv`, "text/csv");
}

export async function exportVerifiedDoc(projectId: number) {
  const claims = await get<Claim[]>(`/claims?project_id=${projectId}`);
  const lines = ["# Verified Document Export", ""];
  let current = "";
  for (const c of claims) {
    if (c.subject_entity !== current) {
      current = c.subject_entity;
      lines.push(`\n## ${current}`);
    }
    lines.push(`- ${c.predicate}: ${c.object_value ?? c.evidence_text.slice(0, 100)}`);
  }
  downloadBlob(lines.join("\n"), `verified_doc_project_${projectId}.md`, "text/plain");
}
