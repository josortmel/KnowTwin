import { useToasts, dismissToast } from "../lib/toast";

const TONE_COLOR: Record<string, string> = {
  success: "var(--grn)",
  error: "var(--red)",
  info: "var(--accent)",
};

// Bottom-center glass toasts. Dot carries the tone (§1.3 — color is the dot, the
// message stays --ink-1); optional action (e.g. Undo) as an ink underline button.
export function Toasts() {
  const toasts = useToasts();
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-5 left-1/2 z-[70] flex -translate-x-1/2 flex-col items-center gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="flex items-center gap-3 rounded-btn px-4 py-2.5"
          style={{ background: "var(--card-bg)", boxShadow: "var(--elev)", backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)" }}
        >
          <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: TONE_COLOR[t.tone], boxShadow: `0 0 6px ${TONE_COLOR[t.tone]}` }} />
          <span className="text-[12.5px] text-ink-1">{t.message}</span>
          {t.action && (
            <button
              type="button"
              onClick={() => {
                t.action!.onClick();
                dismissToast(t.id);
              }}
              className="ml-1 font-mono text-[11px] font-semibold text-ink-1 underline underline-offset-2 hover:text-ink-2"
            >
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
