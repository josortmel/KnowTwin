import { SafeText } from '../../components/SafeText';
import { CorroborationBadge } from '../../components/CorroborationBadge';
import type { TwinSource } from '../../hooks/useTwin';

interface Props {
  sources: TwinSource[];
}

export default function SourcePanel({ sources }: Props) {
  if (sources.length === 0) {
    return <div className="text-gray-400 text-sm p-4">No sources</div>;
  }

  return (
    <div className="space-y-3 p-4">
      <h3 className="font-semibold text-sm text-gray-700">
        <SafeText text={`Sources (${sources.length})`} />
      </h3>
      {sources.map((s, i) => (
        <div key={s.claim_id} className="border rounded p-3 text-sm" id={`source-${i + 1}`}>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-blue-700">
              <SafeText text={`[${i + 1}]`} />
            </span>
            <span className="font-medium">
              <SafeText text={s.subject_entity} />
            </span>
            <span className="text-gray-400">
              <SafeText text={s.predicate} />
            </span>
            <CorroborationBadge level={s.corroboration_level} />
          </div>
          <div className="text-gray-600 mt-1">
            <SafeText text={s.evidence_text} />
          </div>
          <div className="flex gap-3 mt-2 text-xs text-gray-400">
            <span><SafeText text={`sensitivity: ${s.sensitivity}`} /></span>
            <span><SafeText text={`score: ${s.score.toFixed(2)}`} /></span>
            <span><SafeText text={`criticality: ${s.criticality.toFixed(1)}`} /></span>
          </div>
        </div>
      ))}
    </div>
  );
}
