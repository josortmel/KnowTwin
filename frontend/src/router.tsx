import { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { SetupPage } from "./pages/SetupPage";
import { InterviewPage } from "./pages/InterviewPage";
import { TwinPage } from "./pages/TwinPage";
import { OntologyPage } from "./pages/OntologyPage";
import { IngestionPage } from "./pages/IngestionPage";
import { ExplorerPage } from "./pages/ExplorerPage";
import { DecisionsPage } from "./pages/DecisionsPage";
import { ProcessesPage } from "./pages/ProcessesPage";
import { ProcessDetailPage } from "./pages/ProcessDetailPage";

// Graph pulls in react-force-graph-2d + d3-force (~200kB). Code-split it so the
// rest of the app doesn't pay for a route the user may never open.
const GraphPage = lazy(() => import("./pages/GraphPage").then((m) => ({ default: m.GraphPage })));

// The glass shell (NavRail + AppBar + Settings drawer) wraps the routed views.
// Views still render their current content inside; the chrome is the new part.
export function AppRouter() {
  return (
    <AppShell>
      <Routes>
        <Route path="/processes" element={<ProcessesPage />} />
        <Route path="/processes/:id" element={<ProcessDetailPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/interview" element={<InterviewPage />} />
        <Route path="/twin" element={<TwinPage />} />
        <Route path="/explorer" element={<ExplorerPage />} />
        <Route path="/ingestion" element={<IngestionPage />} />
        <Route path="/ontology" element={<OntologyPage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route
          path="/graph"
          element={
            <Suspense fallback={<div className="grid h-full place-items-center font-mono text-[12px] text-ink-3">Loading graph…</div>}>
              <GraphPage />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate to="/processes" replace />} />
      </Routes>
    </AppShell>
  );
}
