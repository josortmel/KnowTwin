import { useEffect, useState } from "react";
import { GlassCard } from "./GlassCard";
import { Button } from "./Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  onConfirm: (note?: string) => void;
  onCancel: () => void;
  confirmLabel?: string;
  destructive?: boolean;
  /** When set, shows a textarea; its trimmed value is passed to onConfirm. */
  notePrompt?: string;
  /** Require a non-empty note before confirm is enabled. */
  noteRequired?: boolean;
}

// Glass modal for privileged/destructive actions (DESIGN.md §3). Closes on
// scrim / Esc. Destructive → muted red button (never a bright fill). Optional
// note/reason input for flows like deletion request / review.
export function ConfirmDialog({
  open,
  title,
  message,
  onConfirm,
  onCancel,
  confirmLabel = "Confirm",
  destructive = false,
  notePrompt,
  noteRequired = false,
}: ConfirmDialogProps) {
  const [note, setNote] = useState("");

  useEffect(() => {
    if (open) setNote("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  const canConfirm = !noteRequired || note.trim().length > 0;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0" style={{ background: "rgba(20,18,14,0.42)" }} onClick={onCancel} />
      <GlassCard className="relative w-full max-w-sm p-6">
        <h3 className="mb-1 text-[15px] font-semibold text-ink-1">{title}</h3>
        <p className="mb-4 text-[13px] leading-relaxed text-ink-2">{message}</p>
        {notePrompt !== undefined && (
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder={notePrompt}
            className="mb-4 w-full resize-none rounded-md px-3 py-2 font-body text-[13px] text-ink-1 outline-none placeholder:text-ink-3"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)" }}
          />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            disabled={!canConfirm}
            onClick={() => onConfirm(notePrompt !== undefined ? note.trim() || undefined : undefined)}
            autoFocus
          >
            {confirmLabel}
          </Button>
        </div>
      </GlassCard>
    </div>
  );
}
