import { useState, useEffect } from "react";
import { get, put } from "../../lib/api";

interface Props {
  projectId: number;
}

export function RetentionPolicy({ projectId }: Props) {
  const [expireDays, setExpireDays] = useState<number | null>(null);
  const [autoExpiry, setAutoExpiry] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    get<{ config: { retention?: { expire_days: number | null; auto_expiry: boolean } } }>(
      `/projects/${projectId}/settings`
    ).then((r) => {
      const ret = r.config.retention;
      if (ret) {
        setExpireDays(ret.expire_days);
        setAutoExpiry(ret.auto_expiry);
      }
    }).catch(() => {});
  }, [projectId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await put(`/projects/${projectId}/settings`, {
        retention: { expire_days: autoExpiry ? expireDays : null, auto_expiry: autoExpiry },
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h3 className="text-sm font-semibold mb-2">Retention Policy</h3>
      <label className="flex items-center gap-2 text-xs mb-2">
        <input
          type="checkbox"
          checked={autoExpiry}
          onChange={(e) => setAutoExpiry(e.target.checked)}
        />
        Auto-expire claims
      </label>
      {autoExpiry && (
        <div className="flex items-center gap-2 text-xs mb-2">
          <span>Expire after</span>
          <input
            type="number"
            min={1}
            max={3650}
            value={expireDays ?? 365}
            onChange={(e) => setExpireDays(parseInt(e.target.value) || 365)}
            className="border rounded px-1 py-0.5 w-20 text-xs"
          />
          <span>days</span>
        </div>
      )}
      <button
        onClick={handleSave}
        disabled={saving}
        className="bg-blue-600 text-white px-3 py-1 rounded text-xs disabled:opacity-50"
      >
        {saving ? "Saving..." : "Save Policy"}
      </button>
    </div>
  );
}
