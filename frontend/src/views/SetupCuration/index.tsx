import { useState } from "react";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { ProcessSetupForm } from "./ProcessSetupForm";
import { DocumentUpload } from "./DocumentUpload";
import { EntitySeedEditor } from "./EntitySeedEditor";
import { CoverageDashboard } from "./CoverageDashboard";
import { CurationInbox } from "./CurationInbox";
import { DisputeQueue } from "./DisputeQueue";
import { AgentConfigPanel } from "./AgentConfigPanel";

const TABS = [
  { id: "setup", label: "Process Setup" },
  { id: "docs", label: "Documents" },
  { id: "entities", label: "Entities" },
  { id: "coverage", label: "Coverage" },
  { id: "inbox", label: "Curation Inbox" },
  { id: "disputes", label: "Disputes" },
  { id: "agents", label: "Agent Config" },
] as const;

type TabId = typeof TABS[number]["id"];

export function SetupCurationView() {
  const [tab, setTab] = useState<TabId>("setup");
  const projectId = 1;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Setup & Curation</h1>
      <nav className="flex gap-1 mb-4 border-b">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition ${
              tab === t.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}>
            {t.label}
          </button>
        ))}
      </nav>
      <ErrorBoundary>
        {tab === "setup" && <ProcessSetupForm />}
        {tab === "docs" && <DocumentUpload projectId={projectId} />}
        {tab === "entities" && <EntitySeedEditor projectId={projectId} />}
        {tab === "coverage" && <CoverageDashboard projectId={projectId} />}
        {tab === "inbox" && <CurationInbox projectId={projectId} />}
        {tab === "disputes" && <DisputeQueue projectId={projectId} />}
        {tab === "agents" && <AgentConfigPanel />}
      </ErrorBoundary>
    </div>
  );
}
