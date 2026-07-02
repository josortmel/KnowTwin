import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { ProcessSetupForm } from "./ProcessSetupForm";
import { DocumentUpload } from "./DocumentUpload";
import { CoverageDashboard } from "./CoverageDashboard";
import { CurationInbox } from "./CurationInbox";
import { DisputeQueue } from "./DisputeQueue";
import { DeletionRequests } from "./DeletionRequests";
import { AgentConfigPanel } from "./AgentConfigPanel";

const TABS = [
  { id: "setup", label: "Process Setup" },
  { id: "docs", label: "Documents" },
  { id: "coverage", label: "Coverage" },
  { id: "inbox", label: "Curation Inbox" },
  { id: "disputes", label: "Disputes" },
  { id: "deletions", label: "Deletions" },
  { id: "agents", label: "Agent Config" },
] as const;

type TabId = typeof TABS[number]["id"];

const TAB_IDS = new Set<string>(TABS.map((t) => t.id));

export function SetupCurationView() {
  const [searchParams] = useSearchParams();
  // Deep-link support: the Dashboard Attention Inbox routes here with ?tab=<id>.
  const initialTab = searchParams.get("tab");
  const [tab, setTab] = useState<TabId>(initialTab && TAB_IDS.has(initialTab) ? (initialTab as TabId) : "setup");
  const projectId = 1;

  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold text-ink-1">Setup &amp; Curation</h1>
      <nav className="mb-4 flex gap-1 border-b" style={{ borderColor: "var(--card-hairline)" }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === t.id ? "border-accent text-ink-1" : "border-transparent text-ink-3 hover:text-ink-2"
            }`}>
            {t.label}
          </button>
        ))}
      </nav>
      <ErrorBoundary>
        {tab === "setup" && <ProcessSetupForm />}
        {tab === "docs" && <DocumentUpload projectId={projectId} />}
        {tab === "coverage" && <CoverageDashboard projectId={projectId} />}
        {tab === "inbox" && <CurationInbox projectId={projectId} />}
        {tab === "disputes" && <DisputeQueue projectId={projectId} />}
        {tab === "deletions" && <DeletionRequests projectId={projectId} />}
        {tab === "agents" && <AgentConfigPanel />}
      </ErrorBoundary>
    </div>
  );
}
