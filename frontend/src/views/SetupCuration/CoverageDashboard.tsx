import { useCoverage } from "../../hooks/useCoverage";
import { SafeText } from "../../components/SafeText";
import { CoverageStateBadge } from "../../components/CoverageStateBadge";
import { Panel, PanelState } from "../../components/Panel";

interface Props {
  projectId: number;
}

export function CoverageDashboard({ projectId }: Props) {
  const { data, isLoading, error } = useCoverage(projectId);

  return (
    <Panel title="Coverage">
      <PanelState loading={isLoading} error={!!error} empty={!!data && data.entities.length === 0} emptyLabel="No coverage data">
        {data && (
          <>
            <div className="mb-3">
              <div className="mb-1 flex justify-between font-mono text-[12px] text-ink-2">
                <span className="uppercase tracking-[0.1em] text-ink-3">Overall coverage</span>
                <span className="tabular-nums text-ink-1">{data.overall_coverage_pct}%</span>
              </div>
              <div className="h-3 w-full overflow-hidden rounded-full" style={{ background: "var(--inset)" }}>
                <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(data.overall_coverage_pct, 100)}%`, background: "var(--chart-bar)" }} />
              </div>
              <p className="mt-1 font-mono text-[10px] text-ink-3">{data.entity_count} entities tracked</p>
            </div>
            {data.entities.length > 0 && (
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b text-left font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3" style={{ borderColor: "var(--card-hairline)" }}>
                    <th className="py-1 font-normal">Entity</th>
                    <th className="font-normal">Type</th>
                    <th className="font-normal">Coverage</th>
                    <th className="font-normal">State</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entities.map((e) => (
                    <tr key={e.entity_name} className="border-b" style={{ borderColor: "var(--card-hairline)" }}>
                      <td className="py-1 text-ink-1">
                        <SafeText text={e.entity_name} />
                      </td>
                      <td className="text-ink-3">
                        <SafeText text={e.entity_type} />
                      </td>
                      <td className="font-mono tabular-nums text-ink-2">{e.coverage_pct}%</td>
                      <td>
                        <CoverageStateBadge state={e.coverage_state} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </PanelState>
    </Panel>
  );
}
