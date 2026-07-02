import { Dot } from "./Dot";

export type ApiStatus = "online" | "degraded" | "offline" | "unknown";

interface StatusPillProps {
  status: ApiStatus;
  latencyMs?: number;
  label?: string;
}

// API-health pill (DESIGN.md §3 chrome). Glow is reserved for signal states
// (online green / offline red); degraded (amber) and unknown carry none.
const MAP: Record<ApiStatus, { color: string; label: string; glow: boolean }> = {
  online: { color: "var(--grn)", label: "Online", glow: true },
  offline: { color: "var(--red)", label: "Offline", glow: true },
  degraded: { color: "var(--cov-partial)", label: "Degraded", glow: false }, // amber, orange reserved for signal
  unknown: { color: "var(--ink-4)", label: "—", glow: false },
};

export function StatusPill({ status, latencyMs, label }: StatusPillProps) {
  const s = MAP[status];
  const showLatency = latencyMs != null && latencyMs > 0;
  return (
    <div
      className="inline-flex items-center gap-[9px] rounded-[20px] px-3 py-1.5 font-mono text-[11px] text-ink-2"
      style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
    >
      <Dot color={s.color} glow={s.glow} />
      <span>{label ?? s.label}</span>
      {showLatency && (
        <>
          <span className="text-ink-4">·</span>
          <span className="text-ink-3">{Math.round(latencyMs)}ms</span>
        </>
      )}
    </div>
  );
}
