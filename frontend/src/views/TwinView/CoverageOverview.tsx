import { SafeText } from '../../components/SafeText';
import { StateBadge } from '../../components/StateBadge';
import { Loading } from '../../components/Loading';
import { EmptyState } from '../../components/EmptyState';
import { useTwinCoverage } from '../../hooks/useTwin';

interface Props {
  projectId: number;
}

export default function CoverageOverview({ projectId }: Props) {
  const { data, isLoading, error } = useTwinCoverage(projectId);

  if (isLoading) return <Loading />;
  if (error) return <div className="text-red-600 text-sm p-4"><SafeText text="Failed to load coverage" /></div>;
  if (!data) return <EmptyState message="No coverage data" />;

  return (
    <div className="p-4">
      <div className="flex items-center gap-4 mb-4">
        <h3 className="font-semibold text-sm text-gray-700">Coverage</h3>
        <div className="flex-1 bg-gray-200 rounded-full h-4 overflow-hidden">
          <div
            className="bg-green-500 h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(data.overall_coverage_pct, 100)}%` }}
          />
        </div>
        <span className="text-sm font-medium">
          <SafeText text={`${data.overall_coverage_pct}%`} />
        </span>
        <span className="text-xs text-gray-400">
          <SafeText text={`${data.entity_count} entities`} />
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
        {data.entities.map((e) => (
          <div key={e.entity_name} className="flex items-center gap-2 text-xs py-1">
            <StateBadge state={e.coverage_state} />
            <span className="truncate"><SafeText text={e.entity_name} /></span>
            <span className="text-gray-400 ml-auto"><SafeText text={`${e.coverage_pct}%`} /></span>
          </div>
        ))}
      </div>
    </div>
  );
}
