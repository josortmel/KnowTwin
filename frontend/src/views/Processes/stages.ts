import type { ProcessStage } from "../../hooks/useProcesses";

// Offboarding pipeline order (api/projects.py stage derivation).
// HR-facing stage labels (§#38). Keys stay as the backend emits them.
export const STAGES: { key: ProcessStage; label: string }[] = [
  { key: "setup", label: "Getting started" },
  { key: "documents", label: "Collecting documents" },
  { key: "curation", label: "Analyzing documents" },
  { key: "interviews", label: "Knowledge transfer" },
  { key: "complete", label: "Handoff ready" },
];

export const stageIndex = (s: string): number => STAGES.findIndex((x) => x.key === s);
