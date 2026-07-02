import { SafeText } from "../../components/SafeText";
import { CoverageStateBadge } from "../../components/CoverageStateBadge";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";
import { Dot } from "../../components/Dot";
import { useTwinCoverage } from "../../hooks/useTwin";

interface Props {
  projectId: number;
}

export default function CoverageOverview({ projectId }: Props) {
  const { data, isLoading, error } = useTwinCoverage(projectId);

  if (isLoading) return <Loading message="Loading coverage…" />;
  if (error)
    return (
      <div className="flex items-center gap-2 p-4">
        <Dot s="alert" glow />
        <span className="font-mono text-[12px] text-ink-2">Failed to load coverage</span>
      </div>
    );
  if (!data) return <EmptyState message="No coverage data" />;

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center gap-4">
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Coverage</h3>
        {/* Monochrome graphite bar (§5) — coverage is data, not signal. */}
        <div className="h-3 flex-1 overflow-hidden rounded-full" style={{ background: "var(--inset)" }}>
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(data.overall_coverage_pct, 100)}%`, background: "var(--chart-bar)" }}
          />
        </div>
        <span className="font-mono text-[13px] font-medium tabular-nums text-ink-1">{data.overall_coverage_pct}%</span>
        <span className="font-mono text-[10px] text-ink-3">{data.entity_count} entities</span>
      </div>
      <div className="grid max-h-48 grid-cols-2 gap-x-4 gap-y-1.5 overflow-y-auto">
        {data.entities.map((e) => (
          <div key={e.entity_name} className="flex items-center gap-2 py-0.5 text-xs">
            <CoverageStateBadge state={e.coverage_state} />
            <SafeText text={e.entity_name} className="truncate font-mono text-[11px] text-ink-2" />
            <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-3">{e.coverage_pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
