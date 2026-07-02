import { useEffect, useState } from "react";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { SegmentedControl } from "../../components/SegmentedControl";
import { SafeText } from "../../components/SafeText";
import type { Dispute, Resolution } from "../../hooks/useDisputes";

interface ResolveDialogProps {
  dispute: Dispute | null;
  onConfirm: (resolution: Resolution, note: string) => void;
  onCancel: () => void;
  submitting?: boolean;
}

const OPTIONS = [
  { value: "in_favor", label: "Claim wins" },
  { value: "against", label: "Counterpart wins" },
];

// Glass modal to resolve a dispute: pick the winning side + a required note.
// The note is deterministic curator text → rendered later via SafeText.
export function ResolveDialog({ dispute, onConfirm, onCancel, submitting }: ResolveDialogProps) {
  const [resolution, setResolution] = useState<Resolution>("in_favor");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (dispute) {
      setResolution("in_favor");
      setNote("");
    }
  }, [dispute]);

  useEffect(() => {
    if (!dispute) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispute, onCancel]);

  if (!dispute) return null;
  const claimObj = dispute.claim.object_entity ?? dispute.claim.object_value ?? "—";
  const cpObj = dispute.counterpart?.object_entity ?? dispute.counterpart?.object_value ?? "—";

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="Resolve dispute">
      <div className="absolute inset-0" style={{ background: "rgba(20,18,14,0.42)" }} onClick={onCancel} />
      <GlassCard className="relative w-full max-w-md p-6">
        <h3 className="mb-1 text-[15px] font-semibold text-ink-1">Resolve dispute</h3>
        <p className="mb-3 flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-2">
          <SafeText text={dispute.claim.subject_entity} className="font-mono text-ink-1" />
          <span className="text-ink-3">·</span>
          <SafeText text={claimObj} className="font-mono text-ink-1" />
          <span className="text-ink-3">vs</span>
          <SafeText text={cpObj} className="font-mono text-ink-1" />
        </p>

        <div className="mb-3">
          <SegmentedControl options={OPTIONS} value={resolution} onChange={(v) => setResolution(v as Resolution)} ariaLabel="Resolution" />
        </div>

        <label className="mb-1 block font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Resolution note (required)</label>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="Why this resolution…"
          className="mb-4 w-full resize-none rounded-md px-3 py-2 font-body text-[13px] text-ink-1 outline-none placeholder:text-ink-3"
          style={{ background: "var(--field-bg)", boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)" }}
        />

        <div className="flex justify-end gap-2">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" loading={submitting} disabled={!note.trim()} onClick={() => onConfirm(resolution, note.trim())}>
            Resolve
          </Button>
        </div>
      </GlassCard>
    </div>
  );
}
