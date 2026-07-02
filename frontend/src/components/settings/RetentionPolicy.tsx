import { useState, useEffect } from "react";
import { get, put } from "../../lib/api";
import { Button } from "../Button";
import { Toggle } from "../Toggle";
import { pushToast } from "../../lib/toast";

interface Props {
  projectId: number;
}

interface RetentionConfig {
  retention_days?: number | null;
  auto_expiry?: boolean;
}

export function RetentionPolicy({ projectId }: Props) {
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [autoExpiry, setAutoExpiry] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    get<{ config: { retention?: RetentionConfig } }>(`/projects/${projectId}/settings`)
      .then((r) => {
        const ret = r.config?.retention;
        if (ret) {
          setRetentionDays(ret.retention_days ?? null);
          setAutoExpiry(!!ret.auto_expiry);
        }
      })
      .catch(() => {});
  }, [projectId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await put(`/projects/${projectId}/settings`, {
        retention: { retention_days: autoExpiry ? retentionDays ?? 365 : null, auto_expiry: autoExpiry },
      });
      pushToast("Retention policy saved", { tone: "success" });
    } catch (e) {
      pushToast(`Save failed: ${e instanceof Error ? e.message : String(e)}`, { tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 font-mono text-[11px] text-ink-2">
        <Toggle on={autoExpiry} onChange={setAutoExpiry} label="Auto-expire claims" />
        Auto-expire claims
      </div>
      {autoExpiry && (
        <div className="mb-2 flex items-center gap-2 font-mono text-[11px] text-ink-2">
          <span>Expire after</span>
          <input
            type="number"
            min={1}
            max={3650}
            value={retentionDays ?? 365}
            onChange={(e) => setRetentionDays(parseInt(e.target.value) || 365)}
            className="w-20 rounded-sm px-2 py-1 font-mono text-[12px] text-ink-1 outline-none"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          />
          <span>days</span>
        </div>
      )}
      <Button variant="primary" onClick={handleSave} loading={saving} className="px-3 py-1.5 text-[12px]">
        Save policy
      </Button>
    </div>
  );
}
