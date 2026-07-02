import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Panel, PanelState } from "../../components/Panel";
import { StatCard } from "../../components/StatCard";
import { Dot } from "../../components/Dot";
import { SafeText } from "../../components/SafeText";
import { useCoverage } from "../../hooks/useCoverage";
import { useDocuments, type Document } from "../../hooks/useDocuments";
import { useSessionList } from "../../hooks/useInterviews";
import { useProjectMembers } from "../../hooks/useProjectMembers";
import {
  useMemoryStats,
  useSystemStats,
  useKnowledgeStats,
  useTimeline,
  useAttentionSummary,
  useAllScores,
  ATTENTION_CLASSES,
} from "../../hooks/useDashboard";

const PROJECT_ID = 1;
const fmt = (n: number | undefined | null): string => (n == null ? "—" : n.toLocaleString("en-US"));

// Command Center — the curator's offboarding hub. Structure ported from EcoDB's
// CommandCenter (12-col bento, glass panels); content is KnowTwin domain: claims,
// disputes (the hottest metric), coverage, docs, knowledge health, activity, and
// interview progress. Monochrome data (§5), signal only via dots (§1.3).
export function DashboardView() {
  const navigate = useNavigate();
  const memory = useMemoryStats();
  const system = useSystemStats();
  const coverage = useCoverage(PROJECT_ID);
  const attention = useAttentionSummary();
  const documents = useDocuments(PROJECT_ID);

  const claimsSub = memory.data?.data?.length
    ? memory.data.data.slice(0, 3).map((d) => `${fmt(d.count)} ${d.label}`).join(" · ")
    : "";
  const docs = documents.data ?? [];
  const indexed = docs.filter((d) => d.status === "indexed").length;
  const disputes = attention.data?.classes.pending_disputes;

  return (
    <>
      <div className="mb-[18px] mt-1.5 px-0.5">
        <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Command Center</h1>
        <p className="mt-1.5 text-[12.5px] text-ink-3">Offboarding knowledge capture — what's captured, what's disputed, and what needs a decision.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:auto-rows-min xl:grid-cols-12">
        <div className="md:col-span-1 xl:col-span-3">
          <StatCard
            label="Claims"
            value={system.data ? fmt(system.data.db.claims_count) : "—"}
            sub={claimsSub}
            loading={system.isPending}
            error={system.isError}
            onClick={() => navigate("/setup?tab=inbox")}
            tooltip="Total claims captured, by source type"
          />
        </div>
        <div className="md:col-span-1 xl:col-span-3">
          <StatCard
            label="Coverage"
            value={coverage.data ? String(Math.round(coverage.data.overall_coverage_pct)) : "—"}
            unit="%"
            sub={coverage.data ? `${coverage.data.entity_count} entities tracked` : ""}
            loading={coverage.isPending}
            error={coverage.isError}
            onClick={() => navigate("/setup?tab=coverage")}
            tooltip="Overall criticality-weighted coverage"
          />
        </div>
        <div className="md:col-span-1 xl:col-span-3">
          <StatCard
            label="Disputes"
            value={disputes != null ? fmt(disputes) : "—"}
            sub="pending resolution"
            accent
            loading={attention.isPending}
            error={attention.isError}
            onClick={() => navigate("/setup?tab=disputes")}
            tooltip="Open disputes needing a resolver — the curator's #1 workflow"
          />
        </div>
        <div className="md:col-span-1 xl:col-span-3">
          <StatCard
            label="Documents"
            value={documents.data ? fmt(docs.length) : "—"}
            sub={documents.data ? `${indexed}/${docs.length} indexed` : ""}
            loading={documents.isPending}
            error={documents.isError}
            onClick={() => navigate("/ingestion")}
            tooltip="Uploaded source documents and index status"
          />
        </div>

        <div className="md:col-span-2 xl:col-span-5 xl:row-span-2">
          <AttentionInbox onNavigate={navigate} />
        </div>
        <div className="md:col-span-2 xl:col-span-4 xl:row-span-2">
          <ActivityFeed />
        </div>
        <div className="md:col-span-1 xl:col-span-3">
          <KnowledgeHealth />
        </div>
        <div className="md:col-span-1 xl:col-span-3">
          <Ingestion onNavigate={navigate} />
        </div>
        <div className="md:col-span-1 xl:col-span-3">
          <InterviewProgress />
        </div>
      </div>
    </>
  );
}

// ── Attention Inbox (the hero — a decision center, not monitoring) ───────────
function InboxDot({ on }: { on: boolean }) {
  return (
    <span className="grid h-[14px] w-[14px] flex-none place-items-center rounded-full" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <span
        className={`h-[6px] w-[6px] rounded-full ${on ? "motion-safe:animate-pulse" : ""}`}
        style={on ? { background: "var(--accent)", boxShadow: "0 0 6px rgba(245,99,30,0.6)" } : { background: "var(--ink-4)", opacity: 0.6 }}
      />
    </span>
  );
}

function AttentionInbox({ onNavigate }: { onNavigate: (to: string) => void }) {
  const q = useAttentionSummary();
  const classes = q.data?.classes;
  const total = q.data?.total ?? 0;

  return (
    <Panel
      title="Attention Inbox"
      accent="var(--accent)"
      tooltip="Decisions waiting on you — disputes, deletions, aliases, stale claims"
      control={
        total > 0 ? (
          <span className="rounded-md px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums text-white" style={{ background: "#b6502f" }}>
            {total}
          </span>
        ) : undefined
      }
    >
      <PanelState loading={q.isPending} error={q.isError} onRetry={() => void q.refetch()} empty={!!classes && total === 0} emptyLabel="All clear — nothing needs your attention">
        <div className="flex flex-col">
          {ATTENTION_CLASSES.map(({ key, label }) => {
            const count = classes?.[key] ?? 0;
            return (
              <button
                key={key}
                type="button"
                onClick={() => onNavigate("/decisions")}
                className="flex items-center gap-3 rounded-md px-2 py-2.5 text-left transition-colors hover:bg-[var(--inset)]"
              >
                <InboxDot on={count > 0} />
                <span className={`flex-1 font-mono text-[12.5px] ${count > 0 ? "text-ink-1" : "text-ink-3"}`}>{label}</span>
                <span
                  className="min-w-[28px] rounded-md px-2 py-0.5 text-center font-mono text-[11px] tabular-nums"
                  style={count > 0 ? { background: "#b6502f", color: "#fff" } : { background: "var(--inset)", color: "var(--ink-2)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => onNavigate("/decisions")}
          className="mt-4 w-full rounded-btn py-2.5 font-body text-[12.5px] font-semibold transition-colors"
          style={{ color: "var(--ink-1)", background: "color-mix(in srgb, var(--accent) 13%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 34%, transparent)" }}
        >
          Review decisions →
        </button>
      </PanelState>
    </Panel>
  );
}

// ── Activity feed (polled timeline, last 7 days) ─────────────────────────────
function ActivityFeed() {
  const q = useTimeline(7);
  const active = (q.data ?? []).filter((d) => d.claims || d.documents || d.searches);

  return (
    <Panel title="Activity" accent="var(--sec-interview)" tag="last 7 days" tooltip="Claims, documents, and searches per day">
      <PanelState loading={q.isPending} error={q.isError} onRetry={() => void q.refetch()} empty={!!q.data && active.length === 0} emptyLabel="No activity yet">
        <div className="flex max-h-[260px] flex-col overflow-y-auto">
          {active.map((d) => (
            <div key={d.date} className="flex items-center gap-3 border-b border-[var(--card-hairline)] py-2.5 last:border-0">
              <span className="flex-none font-mono text-[10.5px] tabular-nums text-ink-3">{new Date(d.date).toLocaleDateString()}</span>
              <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
                {d.claims > 0 && <ActivityCount label="claims" n={d.claims} />}
                {d.documents > 0 && <ActivityCount label="docs" n={d.documents} />}
                {d.searches > 0 && <ActivityCount label="queries" n={d.searches} />}
              </div>
            </div>
          ))}
        </div>
      </PanelState>
    </Panel>
  );
}

function ActivityCount({ label, n }: { label: string; n: number }) {
  return (
    <span className="rounded-sm px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink-2" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      {n} {label}
    </span>
  );
}

// ── Knowledge health (real /api/v1/stats/knowledge — super-only) ─────────────
function HealthStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md p-2 text-center" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="font-mono text-[14px] tabular-nums text-ink-1">{value}</div>
      <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.06em] text-ink-3">{label}</div>
    </div>
  );
}

function KnowledgeHealth() {
  const q = useKnowledgeStats();
  const k = q.data;
  return (
    <Panel title="Knowledge Health" accent="var(--sec-graph)" tag="graph" tooltip="Entity/graph integrity metrics (super-only)">
      <PanelState loading={q.isPending} error={q.isError} onRetry={() => void q.refetch()} empty={!k}>
        {k && (
          <>
            <div className="grid grid-cols-3 gap-2">
              <HealthStat label="Entities" value={fmt(k.entity_count)} />
              <HealthStat label="Orphans" value={fmt(k.orphan_entity_count)} />
              <HealthStat label="Density" value={(k.graph_density ?? 0).toFixed(4)} />
              <HealthStat label="Stale" value={fmt(k.stale_claim_count)} />
              <HealthStat label="Dormant" value={fmt(k.dormant_claim_count)} />
              <HealthStat label="Dupes" value={fmt(k.duplicate_candidate_count)} />
            </div>
            <div className="mt-3">
              <div className="mb-1.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">Top entities by degree</div>
              <div className="flex flex-col gap-1">
                {(k.top_entities_by_degree ?? []).slice(0, 5).map((e) => (
                  <div key={e.id} className="flex items-center gap-2 text-[11.5px]">
                    <span className="min-w-0 flex-1 truncate text-ink-1">
                      <SafeText text={e.name} />
                    </span>
                    <span className="flex-none font-mono text-[9.5px] text-ink-3">
                      <SafeText text={e.type} />
                    </span>
                    <span className="w-[30px] flex-none text-right font-mono text-[10px] tabular-nums text-ink-2">{e.degree}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </PanelState>
    </Panel>
  );
}

// ── Ingestion snapshot (aggregate /documents by status) ──────────────────────
const ING_STAGES: { key: "pending" | "processing" | "indexed" | "duplicate" | "error"; tone?: "proc" | "err" }[] = [
  { key: "pending" },
  { key: "processing", tone: "proc" },
  { key: "indexed" },
  { key: "duplicate" },
  { key: "error", tone: "err" },
];

function Ingestion({ onNavigate }: { onNavigate: (to: string) => void }) {
  const q = useDocuments(PROJECT_ID);
  const { counts, total } = useMemo(() => {
    const docs: Document[] = q.data ?? [];
    const counts = { pending: 0, processing: 0, indexed: 0, duplicate: 0, error: 0 };
    for (const d of docs) {
      if (d.status === "pending") counts.pending++;
      else if (d.status === "processing") counts.processing++;
      else if (d.status === "indexed") counts.indexed++;
      else if (d.status === "duplicate") counts.duplicate++;
      else if (d.status === "failed") counts.error++;
    }
    return { counts, total: docs.length };
  }, [q.data]);

  return (
    <Panel title="Ingestion" accent="var(--sec-setup)" tag="docling" tooltip="Documents by processing stage">
      <PanelState loading={q.isPending} error={q.isError} onRetry={() => void q.refetch()} empty={!!q.data && total === 0} emptyLabel="No documents uploaded">
        <div className="grid grid-cols-5 gap-2">
          {ING_STAGES.map((s) => (
            <div key={s.key} className="min-w-0 rounded-sm py-2.5 text-center" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
              <div className="font-mono text-[16px] tabular-nums text-ink-1">{counts[s.key]}</div>
              <div className="mt-0.5 flex items-center justify-center gap-1 font-mono text-[9.5px] uppercase tracking-[0.04em] text-ink-3">
                {s.tone === "proc" && <Dot s="on" size={4} anim="pulse" />}
                {s.tone === "err" && <Dot s="alert" size={4} />}
                {s.key}
              </div>
            </div>
          ))}
        </div>
        {total === 100 && <div className="mt-1.5 text-center font-mono text-[9.5px] text-ink-3">Showing first 100 — counts may undercount</div>}
        <button
          type="button"
          onClick={() => onNavigate("/ingestion")}
          className="mt-3 w-full rounded-btn py-2 font-body text-[12px] font-semibold"
          style={{ color: "var(--ink-1)", background: "color-mix(in srgb, var(--sec-setup) 13%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-setup) 34%, transparent)" }}
        >
          Manage documents →
        </button>
      </PanelState>
    </Panel>
  );
}

// ── Interview progress (KnowTwin-specific — offboarding sessions + scores) ────
function InterviewProgress() {
  const sessions = useSessionList(PROJECT_ID);
  const scores = useAllScores(PROJECT_ID);
  const members = useProjectMembers(PROJECT_ID);

  const list = sessions.data ?? [];
  const active = list.filter((s) => s.status === "in_progress").length;
  const done = list.filter((s) => s.status === "completed" || s.status === "closed").length;

  const ranked = [...(scores.data ?? [])].sort((a, b) => b.score - a.score);
  const top = ranked[0];
  const nameFor = (id: number) => members.data?.find((m) => m.user_id === id)?.name ?? `Employee #${id}`;
  const solo = ranked.length > 0 && ranked.length <= 2;

  return (
    <Panel title="Interview Progress" accent="var(--sec-twin)" tag="offboarding" tooltip="Interview sessions and knowledge-capture completeness (process framing)">
      <PanelState loading={sessions.isPending} error={sessions.isError} onRetry={() => void sessions.refetch()} empty={!!sessions.data && list.length === 0} emptyLabel="No interview sessions yet">
        <div className="flex gap-2">
          <div className="flex-1 rounded-md p-2 text-center" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
            <div className="flex items-center justify-center gap-1.5 font-mono text-[18px] tabular-nums text-ink-1">
              {active > 0 && <span className="h-[6px] w-[6px] rounded-full motion-safe:animate-pulse" style={{ background: "var(--accent)", boxShadow: "0 0 6px rgba(245,99,30,0.6)" }} />}
              {active}
            </div>
            <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.06em] text-ink-3">Active</div>
          </div>
          <div className="flex-1 rounded-md p-2 text-center" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
            <div className="font-mono text-[18px] tabular-nums text-ink-1">{done}</div>
            <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.06em] text-ink-3">Completed</div>
          </div>
        </div>

        <div className="mt-3">
          <div className="mb-1.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">Capture completeness</div>
          {scores.isError ? (
            <p className="font-mono text-[11px] text-ink-3">Scores unavailable</p>
          ) : !top ? (
            <p className="font-mono text-[11px] text-ink-3">No scores yet</p>
          ) : (
            <>
              <div className="flex items-center gap-2 text-[12px]">
                <span className="min-w-0 flex-1 truncate text-ink-1">
                  <SafeText text={nameFor(top.employee_id)} />
                </span>
                <span className="flex-none font-mono text-[9.5px] text-ink-3">{top.claim_count} claims</span>
                <span className="w-[46px] flex-none text-right font-mono text-[13px] tabular-nums text-ink-1">{top.score.toFixed(2)}</span>
              </div>
              {solo && (
                <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[9.5px] text-ink-3">
                  <span>coverage {top.components.coverage_contrib.toFixed(2)}</span>
                  <span>contradiction {top.components.contradiction_yield.toFixed(2)}</span>
                  <span>quality {top.components.quality.toFixed(2)}</span>
                  <span>gaming −{top.components.gaming_penalty.toFixed(2)}</span>
                </div>
              )}
            </>
          )}
        </div>
      </PanelState>
    </Panel>
  );
}
