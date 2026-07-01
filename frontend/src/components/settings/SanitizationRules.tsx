import { useState, useEffect } from "react";
import { get, put } from "../../lib/api";

const ENTITY_TYPES = [
  "persona_interna", "persona_externa", "cliente_cuenta", "proveedor",
  "proyecto", "sistema_componente", "tecnologia", "decision_tecnica",
  "riesgo", "deuda_tecnica", "acuerdo_informal", "procedimiento_operativo",
  "fuente_sesion",
] as const;

const SENSITIVITY_OPTIONS = ["public", "team", "restricted"] as const;

interface Props {
  projectId: number;
}

export function SanitizationRules({ projectId }: Props) {
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    get<{ config: { sanitization_defaults?: Record<string, string> } }>(
      `/projects/${projectId}/settings`
    ).then((r) => setDefaults(r.config.sanitization_defaults ?? {}))
     .catch(() => {});
  }, [projectId]);

  const handleChange = (type: string, value: string) => {
    setDefaults((prev) => ({ ...prev, [type]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await put(`/projects/${projectId}/settings`, {
        sanitization_defaults: defaults,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h3 className="text-sm font-semibold mb-2">Default Sensitivity by Entity Type</h3>
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {ENTITY_TYPES.map((type) => (
          <div key={type} className="flex items-center justify-between text-xs">
            <span className="font-mono">{type}</span>
            <select
              value={defaults[type] ?? "restricted"}
              onChange={(e) => handleChange(type, e.target.value)}
              className="border rounded px-1 py-0.5 text-xs"
            >
              {SENSITIVITY_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <button
        onClick={handleSave}
        disabled={saving}
        className="mt-2 bg-blue-600 text-white px-3 py-1 rounded text-xs disabled:opacity-50"
      >
        {saving ? "Saving..." : "Save Defaults"}
      </button>
    </div>
  );
}
