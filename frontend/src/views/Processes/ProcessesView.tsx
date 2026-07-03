import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { SafeText } from "../../components/SafeText";
import { Dot } from "../../components/Dot";
import { pushToast } from "../../lib/toast";
import { useWorkspaceProjects, useProjectStatus, useProjectNextSteps, useCreateProcess, type WorkspaceProject } from "../../hooks/useProcesses";
import { STAGES, stageIndex } from "./stages";

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

// Days until an ISO date (YYYY-MM-DD); null if unset/invalid.
function daysUntil(iso?: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.ceil((t - Date.now()) / 86_400_000);
}

// Traffic light: green = healthy, amber = attention, red = at risk.
function trafficColor(coverage: number, openDisputes: number, days: number | null): string {
  if (coverage < 40 || (days != null && days < 7)) return "var(--red)";
  if (coverage > 80 && openDisputes === 0) return "var(--grn)";
  return "var(--sec-decisions)";
}

function StageBadge({ stage }: { stage: string }) {
  const label = STAGES.find((s) => s.key === stage)?.label ?? stage;
  const done = stage === "complete";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-2"
      style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
    >
      <Dot s={done ? "ok" : "idle"} size={5} />
      {label}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="font-mono text-[15px] tabular-nums text-ink-1">{value}</div>
      <div className="font-mono text-[9px] uppercase tracking-[0.08em] text-ink-3">{label}</div>
    </div>
  );
}

function ProcessCard({ project }: { project: WorkspaceProject }) {
  const status = useProjectStatus(project.id);
  const nextSteps = useProjectNextSteps(project.id);
  const idx = status.data ? stageIndex(status.data.stage) : 0;
  const progress = ((idx + (status.data?.stage === "complete" ? 1 : 0)) / STAGES.length) * 100;

  const days = daysUntil(project.exit_date);
  const light = status.data ? trafficColor(status.data.coverage_pct, status.data.open_disputes ?? 0, days) : "var(--ink-4)";
  const nextLabel = nextSteps.data?.[0]?.label;

  return (
    <Link to={`/processes/${project.id}`} className="block">
      <GlassCard className="p-card-lg transition-transform hover:-translate-y-0.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="h-[9px] w-[9px] flex-none rounded-full" style={{ background: light, boxShadow: `0 0 6px ${light}` }} aria-hidden />
              <SafeText text={project.employee_name || project.name} className="truncate font-body text-[15px] font-semibold text-ink-1" />
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[10.5px] text-ink-3">
              {project.department && <SafeText text={project.department} />}
              {project.exit_date && (
                <span>Exits {project.exit_date}{days != null ? ` (${days} day${days === 1 ? "" : "s"})` : ""}</span>
              )}
            </div>
            <div className="mt-1.5">
              {status.isPending ? (
                <span className="inline-block h-[18px] w-24 animate-pulse rounded-full motion-reduce:animate-none" style={{ background: "var(--inset)" }} />
              ) : status.isError ? (
                <span className="font-mono text-[10px] text-ink-3">status unavailable</span>
              ) : (
                <StageBadge stage={status.data!.stage} />
              )}
            </div>
          </div>
          <span className="flex-none font-mono text-[11px] tabular-nums text-ink-3">{status.data ? `${status.data.coverage_pct}%` : "—"}</span>
        </div>

        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--inset)" }}>
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(progress, 100)}%`, background: "var(--accent)" }} />
        </div>

        <div className="mt-3 grid grid-cols-4 gap-2">
          <Metric label="Documents" value={status.data ? String(status.data.documents) : "—"} />
          <Metric label="Knowledge items" value={status.data ? String(status.data.claims) : "—"} />
          <Metric label="Sessions" value={status.data ? `${status.data.completed_sessions}/${status.data.sessions}` : "—"} />
          <Metric label="Completeness" value={status.data ? `${status.data.coverage_pct}%` : "—"} />
        </div>

        {nextLabel && (
          <div className="mt-3 truncate border-t pt-2.5 font-mono text-[11px] text-ink-2" style={{ borderColor: "var(--card-hairline)" }}>
            <span className="text-ink-3">Next: </span><SafeText text={nextLabel} />
          </div>
        )}
      </GlassCard>
    </Link>
  );
}

function NewProcessWizard({ onClose }: { onClose: () => void }) {
  const create = useCreateProcess();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [department, setDepartment] = useState("");
  const [exitDate, setExitDate] = useState("");
  const [disposition, setDisposition] = useState("");
  const [manager, setManager] = useState("");
  const [replacement, setReplacement] = useState("");
  const [priority, setPriority] = useState("routine");
  const [areas, setAreas] = useState("");
  const canCreate = name.trim().length > 0 && !create.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canCreate) return;
    create.mutate(
      {
        employeeName: name.trim(),
        role: role.trim(),
        department: department.trim(),
        exitDate: exitDate.trim(),
        disposition: disposition.trim(),
        reportingManager: manager.trim(),
        replacementName: replacement.trim(),
        priority,
        knowledgeAreas: areas.split(",").map((a) => a.trim()).filter(Boolean),
      },
      {
        onSuccess: (proj) => {
          pushToast("Offboarding process created", { tone: "success" });
          navigate(`/processes/${proj.id}`);
        },
        onError: (e) => pushToast(`Create failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  const field = { background: "var(--field-bg)", boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)" } as const;
  const cls = "rounded-md px-2.5 py-2 font-body text-[13px] text-ink-1 outline-none placeholder:text-ink-3";
  const lbl = "font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3";
  return (
    <GlassCard className="p-card-lg">
      <h3 className="mb-3 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">New offboarding process</h3>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1"><span className={lbl}>Employee name</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Juan Garcia" className={cls} style={field} /></label>
        <label className="flex flex-col gap-1"><span className={lbl}>Role</span><input value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Data Engineer" className={cls} style={field} /></label>
        <label className="flex flex-col gap-1"><span className={lbl}>Department</span><input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="e.g. Engineering" className={cls} style={field} /></label>
        <label className="flex flex-col gap-1"><span className={lbl}>Exit date</span><input value={exitDate} onChange={(e) => setExitDate(e.target.value)} type="date" className={cls} style={field} /></label>
        <label className="flex flex-col gap-1"><span className={lbl}>Reporting manager</span><input value={manager} onChange={(e) => setManager(e.target.value)} placeholder="Manager name" className={cls} style={field} /></label>
        <label className="flex flex-col gap-1"><span className={lbl}>Replacement</span><input value={replacement} onChange={(e) => setReplacement(e.target.value)} placeholder="Successor (if any)" className={cls} style={field} /></label>
        <label className="flex flex-col gap-1"><span className={lbl}>Priority</span>
          <select value={priority} onChange={(e) => setPriority(e.target.value)} className={cls} style={field}>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
            <option value="emergency">Emergency</option>
          </select>
        </label>
        <label className="flex flex-col gap-1"><span className={lbl}>Reason for leaving</span><input value={disposition} onChange={(e) => setDisposition(e.target.value)} placeholder="e.g. Voluntary, Retirement" className={cls} style={field} /></label>
        <label className="col-span-2 flex flex-col gap-1"><span className={lbl}>Key knowledge areas</span><input value={areas} onChange={(e) => setAreas(e.target.value)} placeholder="Comma-separated — e.g. ETL Pipeline, Billing System" className={cls} style={field} /></label>
        <div className="col-span-2 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-2 font-body text-[13px] text-ink-2 hover:text-ink-1" style={field}>Cancel</button>
          <Button type="submit" variant="primary" disabled={!canCreate} loading={create.isPending}>Create process</Button>
        </div>
      </form>
    </GlassCard>
  );
}

export function ProcessesView() {
  const projects = useWorkspaceProjects();
  const [wizard, setWizard] = useState(false);

  return (
    <>
      <div className="mb-[18px] mt-1.5 flex items-end justify-between gap-4 px-0.5">
        <div>
          <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Processes</h1>
          <p className="mt-1.5 text-[12.5px] text-ink-3">Offboarding knowledge capture — one process per departing employee.</p>
        </div>
        {!wizard && (
          <Button variant="primary" onClick={() => setWizard(true)} className="flex-none">New process</Button>
        )}
      </div>

      {wizard && <div className="mb-4"><NewProcessWizard onClose={() => setWizard(false)} /></div>}

      {projects.isPending ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {[0, 1].map((i) => <div key={i} className="h-40 animate-pulse rounded-lg motion-reduce:animate-none" style={{ background: "var(--inset)" }} />)}
        </div>
      ) : projects.isError ? (
        <GlassCard className="p-[18px]"><div className="flex items-center gap-2 font-mono text-[12.5px] text-ink-3"><Dot s="alert" glow /> Couldn't load processes</div></GlassCard>
      ) : (projects.data?.length ?? 0) === 0 ? (
        <GlassCard className="p-[18px]">
          <div className="py-10 text-center">
            <div className="text-[13.5px] text-ink-1">No offboarding processes yet.</div>
            <div className="mt-1 text-[12px] text-ink-3">Start one to capture a departing employee's knowledge.</div>
            {!wizard && <Button variant="primary" onClick={() => setWizard(true)} className="mt-4">New process</Button>}
          </div>
        </GlassCard>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {projects.data!.map((p) => <ProcessCard key={p.id} project={p} />)}
        </div>
      )}
    </>
  );
}
