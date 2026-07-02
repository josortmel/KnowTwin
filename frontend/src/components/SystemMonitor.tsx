import { useState, type ReactNode } from "react";
import { useSystemStats } from "../hooks/useDashboard";

const ACCENT = "var(--sec-settings)"; // neutral/ambient slate

const fmtNum = (n?: number): string => (n != null ? n.toLocaleString("en-US") : "—");

function Chevron({ up }: { up: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={13} height={13} style={{ transform: up ? "rotate(180deg)" : undefined, transition: "transform .15s ease-out" }}>
      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Metric({ label, value, color }: { label: string; value: ReactNode; color: string }) {
  return (
    <div className="min-w-[90px] flex-1 rounded-md px-3 py-2" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="flex items-center gap-1.5">
        <span className="h-[6px] w-[6px] flex-none rounded-full" style={{ background: color }} />
        <span className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">{label}</span>
      </div>
      <div className="mt-1 font-mono text-[15px] leading-none tabular-nums text-ink-1">{value}</div>
    </div>
  );
}

// Bottom status strip — proves the system is alive. Handle always visible; click
// expands the metrics. No agent presence (stripped in KnowTwin) — embeddings health
// + DB counts only.
export function SystemMonitor() {
  const [expanded, setExpanded] = useState(false);
  const sys = useSystemStats();
  const db = sys.data?.db;
  const emb = sys.data?.embeddings;

  const embReady = emb?.status === "ok";
  const embColor = !emb ? "var(--ink-4)" : embReady ? "var(--grn)" : "var(--red)";
  const embLabel = !emb ? "—" : embReady ? "online" : emb.status;

  return (
    <div className="flex flex-none flex-col overflow-hidden rounded-xl" style={{ background: "var(--tray-bg)", backdropFilter: "blur(22px) saturate(1.3)", WebkitBackdropFilter: "blur(22px) saturate(1.3)", boxShadow: "var(--tray-shadow)" }}>
      {expanded && (
        <div className="flex flex-wrap gap-2 px-6 pb-2.5 pt-3">
          <Metric label="Claims" value={sys.isPending ? "…" : fmtNum(db?.claims_count)} color={ACCENT} />
          <Metric label="Nodes" value={sys.isPending ? "…" : fmtNum(db?.nodes_count)} color={ACCENT} />
          <Metric label="Triples" value={sys.isPending ? "…" : fmtNum(db?.triples_count)} color={ACCENT} />
          <Metric label="Embeddings" value={sys.isPending ? "…" : embLabel} color={embColor} />
        </div>
      )}

      <button type="button" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded} aria-label={expanded ? "Collapse system monitor" : "Expand system monitor"} className="flex h-[30px] flex-none items-center gap-3 px-6 text-left transition-colors hover:bg-[var(--inset)]">
        <span className="flex items-center gap-2">
          <span className="h-[6px] w-[6px] rounded-full motion-safe:animate-pulse" style={{ background: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
          <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-2">System</span>
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[9.5px] text-ink-3">
          <span className="h-[5px] w-[5px] rounded-full" style={{ background: embColor, boxShadow: embColor !== "var(--ink-4)" ? `0 0 4px ${embColor}` : undefined }} />
          embeddings {embLabel}
        </span>
        {db && <span className="font-mono text-[9.5px] text-ink-3">{fmtNum(db.claims_count)} claims · {fmtNum(db.nodes_count)} nodes</span>}
        <span className="ml-auto text-ink-3">
          <Chevron up={!expanded} />
        </span>
      </button>
    </div>
  );
}
