import { useState } from "react";
import { setApiKey, clearApiKey, hasApiKey } from "../lib/auth";
import { Button } from "./Button";
import { Dot } from "./Dot";
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
    <div className="mb-2 rounded-md" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-3 py-2 text-left font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-2 transition-colors hover:text-ink-1"
      >
        {title}
        <span className="text-[10px] text-ink-3">{expanded ? "▼" : "▶"}</span>
      </button>
      {expanded && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export function SettingsDrawer({ open, onClose, projectId = 1 }: Props) {
  // The key is stored encrypted in main and never readable from the renderer,
  // so the field starts empty; `hasApiKey()` tells us whether one is configured.
  const [key, setKey] = useState("");
  const [keyError, setKeyError] = useState<string | null>(null);
  const configured = hasApiKey();

  const saveKey = async () => {
    setKeyError(null);
    try {
      const ok = await setApiKey(key.trim());
      if (ok) onClose();
      else setKeyError("Could not store the key — encryption may be unavailable.");
    } catch {
      setKeyError("Could not store the key — encryption may be unavailable.");
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0" style={{ background: "rgba(20,18,14,0.42)" }} onClick={onClose} />
      <div
        className="relative h-full w-96 overflow-y-auto p-4"
        style={{
          background: "var(--card-bg)",
          backdropFilter: "blur(28px) saturate(1.4)",
          WebkitBackdropFilter: "blur(28px) saturate(1.4)",
          boxShadow: "var(--elev-hi)",
        }}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-ink-1">Settings</h2>
          <button type="button" onClick={onClose} className="text-xl leading-none text-ink-3 transition-colors hover:text-ink-1">
            &times;
          </button>
        </div>

        <Section title="API Key" defaultOpen>
          <label className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">
            API Key {configured && <Dot s="ok" size={5} />}
          </label>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={configured ? "Enter a new key to replace" : "Enter API key"}
            className="mb-2 w-full rounded-sm px-2 py-1.5 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)" }}
          />
          <div className="flex gap-2">
            <Button variant="primary" onClick={saveKey} disabled={!key.trim()} className="px-3 py-1.5 text-[12px]">
              Save
            </Button>
            <Button
              variant="default"
              onClick={async () => {
                await clearApiKey();
                setKey("");
                setKeyError(null);
              }}
              className="px-3 py-1.5 text-[12px]"
            >
              Clear
            </Button>
          </div>
          {keyError && <p className="mt-2 text-[11px] text-ink-2">{keyError}</p>}
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
