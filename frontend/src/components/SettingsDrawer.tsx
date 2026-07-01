import { useState } from "react";
import { setApiKey, getApiKey, clearApiKey } from "../lib/auth";
import { SanitizationRules } from "./settings/SanitizationRules";
import { RetentionPolicy } from "./settings/RetentionPolicy";
import { SttConfig } from "./settings/SttConfig";
import { ExportPanel } from "./settings/ExportPanel";

interface Props {
  open: boolean;
  onClose: () => void;
  projectId?: number;
}

function Section({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [expanded, setExpanded] = useState(defaultOpen);
  return (
    <div className="border rounded mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-3 py-2 text-sm font-medium hover:bg-gray-50 flex justify-between items-center"
      >
        {title}
        <span className="text-xs text-gray-400">{expanded ? "▼" : "▶"}</span>
      </button>
      {expanded && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export function SettingsDrawer({ open, onClose, projectId = 1 }: Props) {
  const [key, setKey] = useState(getApiKey() ?? "");

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-96 bg-white h-full shadow-lg p-4 overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">Settings</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        <Section title="API Key" defaultOpen>
          <label className="block text-xs font-medium mb-1">API Key</label>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className="w-full border rounded px-2 py-1 mb-2 text-sm"
          />
          <div className="flex gap-2">
            <button
              onClick={() => { setApiKey(key); onClose(); }}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs"
            >
              Save
            </button>
            <button
              onClick={() => { clearApiKey(); setKey(""); }}
              className="border px-3 py-1 rounded text-xs"
            >
              Clear
            </button>
          </div>
        </Section>

        <Section title="Sanitization Defaults">
          <SanitizationRules projectId={projectId} />
        </Section>

        <Section title="Retention Policy">
          <RetentionPolicy projectId={projectId} />
        </Section>

        <Section title="STT Configuration">
          <SttConfig projectId={projectId} />
        </Section>

        <Section title="Export">
          <ExportPanel projectId={projectId} />
        </Section>
      </div>
    </div>
  );
}
