import { useEffect, useState } from "react";
import { useClaimAudit, type AuditEntry } from "../hooks/useClaimAudit";
import { SafeText } from "./SafeText";
import { Chip } from "./Chip";
import { PanelState } from "./Panel";

// "audit" drawer kind → slate hue (§7.5 settings) for the kicker + wash.
const KICKER = "var(--sec-settings)";

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} width={15} height={15}>
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  );
}

function prettyDetails(raw?: string | null): string {
  if (!raw) return "";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function EntryRow({ entry, last }: { entry: AuditEntry; last: boolean }) {
  const [open, setOpen] = useState(false);
  const time = new Date(entry.timestamp).toLocaleString("en-US", { hour12: false });
  const details = prettyDetails(entry.details);
  return (
    <div className="relative pb-5 pl-5">
      <span className="absolute left-0 top-1.5 h-[8px] w-[8px] rounded-full" style={{ background: KICKER, boxShadow: `0 0 6px ${KICKER}` }} />
      {!last && <span className="absolute bottom-0 left-[3.5px] top-4 w-px" style={{ background: "var(--card-hairline)" }} />}
      <div className="flex items-center gap-2">
        <Chip>{entry.action}</Chip>
        <span className="font-mono text-[10px] text-ink-3">user {entry.user_id ?? "—"}</span>
      </div>
      <div className="mt-1 font-mono text-[10px] tabular-nums text-ink-3">{time}</div>
      {details && (
        <>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="mt-1 font-mono text-[10px] text-ink-2 underline underline-offset-2 transition-colors hover:text-ink-1"
          >
            {open ? "hide details" : "details"}
          </button>
          {open && (
            <SafeText
              text={details}
              as="pre"
              className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-sm p-2 font-mono text-[10.5px] leading-relaxed text-ink-1"
            />
          )}
        </>
      )}
    </div>
  );
}

interface AuditDrawerProps {
  open: boolean;
  claimId: string | null;
  onClose: () => void;
}

// Right-side glass drawer (DESIGN.md §3, EcoDB pattern): kicker + dot + hue wash.
// Shows a claim's audit timeline (oldest first). All text via SafeText.
export function AuditDrawer({ open, claimId, onClose }: AuditDrawerProps) {
  const { data, isLoading, error } = useClaimAudit(open ? claimId : null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const entries = (data ?? []).slice().sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-[60] transition-opacity duration-300 ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        style={{ background: "rgba(18,14,10,0.34)", backdropFilter: "blur(3px)", WebkitBackdropFilter: "blur(3px)" }}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Audit trail"
        className="fixed right-0 top-0 z-[61] flex h-screen w-[408px] max-w-[92vw] flex-col transition-transform duration-300"
        style={{
          transform: open ? "translateX(0)" : "translateX(110%)",
          background: "var(--card-bg)",
          backdropFilter: "blur(var(--drawer-blur)) saturate(1.6)",
          WebkitBackdropFilter: "blur(var(--drawer-blur)) saturate(1.6)",
          boxShadow: "-1px 0 0 var(--card-edge) inset, -40px 0 70px -26px rgba(0,0,0,0.5)",
        }}
      >
        {/* 7% hue wash at the top of the panel */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-40" style={{ background: `linear-gradient(180deg, color-mix(in srgb, ${KICKER} 7%, transparent), transparent)` }} />
        <div className="relative flex items-start justify-between p-5">
          <div>
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2">
              <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: KICKER, boxShadow: `0 0 8px ${KICKER}` }} />
              Audit trail
            </div>
            <div className="mt-2 font-mono text-[12px] text-ink-2">{entries.length} entries</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="grid h-[30px] w-[30px] flex-none place-items-center rounded-md text-ink-2 transition-colors hover:text-ink-1"
            style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="relative min-h-0 flex-1 overflow-y-auto px-5 pb-6">
          <PanelState
            loading={isLoading}
            error={!!error}
            empty={!isLoading && !error && entries.length === 0}
            emptyLabel="No audit entries"
          >
            <div className="pt-1">
              {entries.map((e, i) => (
                <EntryRow key={e.id} entry={e} last={i === entries.length - 1} />
              ))}
            </div>
          </PanelState>
        </div>
      </aside>
    </>
  );
}
