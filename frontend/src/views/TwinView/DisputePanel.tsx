import { SafeText } from '../../components/SafeText';
import { CorroborationBadge } from '../../components/CorroborationBadge';
import type { DisputeGroup } from '../../hooks/useTwin';

interface Props {
  disputes: DisputeGroup[];
}

export default function DisputePanel({ disputes }: Props) {
  if (disputes.length === 0) {
    return <div className="text-gray-400 text-sm p-4">No active disputes</div>;
  }

  return (
    <div className="space-y-4 p-4">
      <h3 className="font-semibold text-sm text-gray-700">
        <SafeText text={`Disputes (${disputes.length})`} />
      </h3>
      {disputes.map((d, i) => (
        <div key={`${d.subject_entity}-${d.predicate}-${i}`} className="border border-red-200 rounded p-3">
          <div className="font-medium text-sm mb-2">
            <SafeText text={`${d.subject_entity} — ${d.predicate}`} />
          </div>
          <div className="space-y-2">
            {d.versions.map((v, vi) => (
              <div key={v.claim_id} className="bg-gray-50 rounded p-2 text-sm">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-gray-500">
                    <SafeText text={`Version ${vi + 1}`} />
                  </span>
                  <CorroborationBadge level={v.corroboration_level} />
                  {v.score > 0 && (
                    <span className="text-xs text-gray-400">
                      <SafeText text={`doc_strength: ${v.score.toFixed(2)}`} />
                    </span>
                  )}
                </div>
                <div className="text-gray-700">
                  <SafeText text={v.evidence_text} />
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
