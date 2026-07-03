import { Link, useParams } from "react-router-dom";
import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { Dot } from "../../components/Dot";
import { useProjectStatus, useProjectNextSteps, type NextStep } from "../../hooks/useProcesses";
import { STAGES, stageIndex } from "./stages";

// Map a next-step action to the view that resolves it.
function stepTarget(step: NextStep): { to: string; cta: string } {
  switch (step.action) {
    case "upload_documents":
      return { to: "/ingestion", cta: "Upload documents" };
    case "run_curator":
      return { to: "/setup?tab=docs", cta: "Process documents" };
    case "schedule_interview":
      return { to: "/interview", cta: "Schedule knowledge transfer" };
    case "cover_gaps": {
      // Gap names are embedded in the label after the colon; prefill the first.
      const after = step.label.split(":")[1] ?? "";
      const topic = after.split(",")[0]?.trim();
      return { to: topic ? `/interview?topic=${encodeURIComponent(topic)}` : "/interview", cta: "Continue interview" };
    }
    case "review_twin":
      return { to: "/twin", cta: "Ask the knowledge assistant" };
    default:
      return { to: "", cta: "" };
  }
}

function StageBar({ stage }: { stage: string }) {
  const current = stageIndex(stage);
  return (
    <div className="flex items-center gap-1.5">
      {STAGES.map((s, i) => {
        const done = i < current || stage === "complete";
        const active = i === current && stage !== "complete";
        return (
          <div key={s.key} className="flex flex-1 items-center gap-1.5">
            <div className="min-w-0 flex-1">
              <div
                className="h-1.5 w-full rounded-full"
                style={{ background: done || active ? "var(--accent)" : "var(--inset)", opacity: done ? 0.55 : 1 }}
              />
              <div className={`mt-1 truncate font-mono text-[10px] uppercase tracking-[0.06em] ${active ? "text-ink-1" : "text-ink-3"}`}>{s.label}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md p-3" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="font-mono text-[18px] tabular-nums text-ink-1">{value}</div>
      <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">{label}</div>
    </div>
  );
}

function NextStepCard({ step }: { step: NextStep }) {
  const { to, cta } = stepTarget(step);
  return (
    <div className="flex items-center justify-between gap-3 rounded-md p-3.5" style={{ background: "color-mix(in srgb, var(--accent) 7%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 22%, transparent)" }}>
      <div className="flex min-w-0 items-start gap-2.5">
        <span className="mt-[5px] h-[7px] w-[7px] flex-none rounded-full" style={{ background: "var(--accent)" }} />
        <SafeText text={step.label} className="text-[13px] leading-snug text-ink-1" />
      </div>
      {to && (
        <Link
          to={to}
          className="flex-none rounded-md px-3 py-1.5 font-body text-[12px] font-semibold text-white transition-[filter] hover:brightness-105"
          style={{ background: "var(--btn-primary)" }}
        >
          {cta}
        </Link>
      )}
    </div>
  );
}

export function ProcessDetailView() {
  const { id } = useParams();
  const projectId = Number(id);
  const status = useProjectStatus(projectId);
  const steps = useProjectNextSteps(projectId);

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 mt-1.5 px-0.5">
        <Link to="/processes" className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-3 transition-colors hover:text-ink-1">
          <span aria-hidden>←</span> All processes
        </Link>
        <h1 className="mt-2 font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">
          <SafeText text={status.data?.project_name ?? "Process"} />
        </h1>
      </div>

      {status.isError ? (
        <GlassCard className="p-[18px]"><div className="flex items-center gap-2 font-mono text-[12.5px] text-ink-3"><Dot s="alert" glow /> Couldn't load this process</div></GlassCard>
      ) : (
        <>
          <GlassCard className="p-card-lg">
            {status.isPending ? (
              <div className="h-10 animate-pulse rounded-md motion-reduce:animate-none" style={{ background: "var(--inset)" }} />
            ) : (
              <StageBar stage={status.data!.stage} />
            )}
            <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <Metric label="Documents" value={status.data ? String(status.data.documents) : "—"} />
              <Metric label="Knowledge items" value={status.data ? String(status.data.claims) : "—"} />
              <Metric label="Sessions" value={status.data ? `${status.data.completed_sessions}/${status.data.sessions}` : "—"} />
              <Metric label="Completeness" value={status.data ? `${status.data.coverage_pct}%` : "—"} />
            </div>
          </GlassCard>

          {!!status.data?.open_disputes && status.data.open_disputes > 0 && (
            <Link to="/decisions" className="mt-4 flex items-center justify-between gap-3 rounded-md p-3.5" style={{ background: "color-mix(in srgb, var(--red) 8%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 25%, transparent)" }}>
              <div className="flex items-center gap-2.5">
                <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: "var(--red)" }} />
                <span className="text-[13px] text-ink-1">{status.data.open_disputes} open dispute{status.data.open_disputes === 1 ? "" : "s"} need a decision</span>
              </div>
              <span className="flex-none font-mono text-[11.5px] text-ink-2">Review disputes →</span>
            </Link>
          )}

          <div className="mb-2 mt-6 px-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Next steps</div>
          <GlassCard className="p-card-lg">
            {steps.isPending ? (
              <div className="flex flex-col gap-2">{[0, 1].map((i) => <div key={i} className="h-12 animate-pulse rounded-md motion-reduce:animate-none" style={{ background: "var(--inset)" }} />)}</div>
            ) : steps.isError ? (
              <div className="font-mono text-[12px] text-ink-3">Couldn't load next steps</div>
            ) : (steps.data?.length ?? 0) === 0 ? (
              <div className="font-mono text-[12px] text-ink-3">Nothing to do right now.</div>
            ) : (
              <div className="flex flex-col gap-2">
                {steps.data!.map((s, i) => <NextStepCard key={`${s.action}-${i}`} step={s} />)}
              </div>
            )}
          </GlassCard>

          <div className="mt-6 flex justify-center">
            <button
              type="button"
              disabled
              title="Coming soon"
              className="rounded-md px-4 py-2 font-body text-[13px] font-semibold text-ink-3"
              style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
            >
              Generate handoff report — coming soon
            </button>
          </div>
        </>
      )}
    </div>
  );
}
