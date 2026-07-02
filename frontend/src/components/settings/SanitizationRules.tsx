import { useState, useEffect } from "react";
import { get, put } from "../../lib/api";
import { Button } from "../Button";
import { pushToast } from "../../lib/toast";

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
    get<{ config: { sanitization_defaults?: Record<string, string> } }>(`/projects/${projectId}/settings`)
      .then((r) => setDefaults(r.config?.sanitization_defaults ?? {}))
      .catch(() => {});
  }, [projectId]);

  const handleChange = (type: string, value: string) => setDefaults((prev) => ({ ...prev, [type]: value }));

  const handleSave = async () => {
    setSaving(true);
    try {
      await put(`/projects/${projectId}/settings`, { sanitization_defaults: defaults });
      pushToast("Sanitization defaults saved", { tone: "success" });
    } catch (e) {
      pushToast(`Save failed: ${e instanceof Error ? e.message : String(e)}`, { tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Default sensitivity by entity type</p>
      <div className="max-h-64 space-y-1 overflow-y-auto">
        {ENTITY_TYPES.map((type) => (
          <div key={type} className="flex items-center justify-between gap-2 font-mono text-[11px] text-ink-2">
            <span>{type}</span>
            <select
              value={defaults[type] ?? "restricted"}
              onChange={(e) => handleChange(type, e.target.value)}
              className="rounded-sm px-1.5 py-0.5 font-mono text-[11px] text-ink-1 outline-none"
              style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
            >
              {SENSITIVITY_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <Button variant="primary" onClick={handleSave} loading={saving} className="mt-2 px-3 py-1.5 text-[12px]">
        Save defaults
      </Button>
    </div>
  );
}
