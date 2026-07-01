import { useState } from "react";
import { setApiKey, getApiKey, clearApiKey } from "../lib/auth";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SettingsDrawer({ open, onClose }: Props) {
  const [key, setKey] = useState(getApiKey() ?? "");

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-80 bg-white h-full shadow-lg p-4 overflow-y-auto">
        <h2 className="text-lg font-semibold mb-4">Settings</h2>

        <label className="block text-sm font-medium mb-1">API Key</label>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          className="w-full border rounded px-2 py-1 mb-2 text-sm"
        />
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => { setApiKey(key); onClose(); }}
            className="bg-blue-600 text-white px-3 py-1 rounded text-sm"
          >
            Save
          </button>
          <button
            onClick={() => { clearApiKey(); setKey(""); }}
            className="border px-3 py-1 rounded text-sm"
          >
            Clear
          </button>
        </div>

        <button onClick={onClose} className="text-sm text-gray-500 hover:underline">
          Close
        </button>
      </div>
    </div>
  );
}
