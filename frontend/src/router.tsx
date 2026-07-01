import { useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { SetupPage } from "./pages/SetupPage";
import { InterviewPage } from "./pages/InterviewPage";
import { TwinPage } from "./pages/TwinPage";
import { SettingsDrawer } from "./components/SettingsDrawer";

export function AppRouter() {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b px-4 py-2 flex items-center justify-between">
        <span className="font-semibold text-lg">KnowTwin</span>
        <div className="flex gap-4">
          <a href="/setup" className="hover:underline">Setup</a>
          <a href="/interview" className="hover:underline">Interview</a>
          <a href="/twin" className="hover:underline">Twin</a>
          <button onClick={() => setSettingsOpen(true)} className="hover:underline">
            Settings
          </button>
        </div>
      </nav>

      <main className="p-4">
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/interview" element={<InterviewPage />} />
          <Route path="/twin" element={<TwinPage />} />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      </main>

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
