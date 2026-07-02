import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import type { TwinSource } from "../../hooks/useTwin";

interface Props {
  sources: TwinSource[];
}

export default function SourcePanel({ sources }: Props) {
  if (sources.length === 0) {
    return <div className="p-4 font-mono text-[12px] text-ink-3">No sources</div>;
  }

  return (
    <div className="space-y-3 p-4">
      <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Sources ({sources.length})</h3>
      {sources.map((s, i) => {
        const b = s.doc_strength_breakdown;
        return (
          <GlassCard key={s.claim_id} className="p-3">
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
              <span className="font-mono text-[11px] text-ink-3">[{i + 1}]</span>
              <SafeText text={s.subject_entity} className="font-mono text-[12px] text-ink-1" />
              <span className="font-mono text-[11px] text-ink-3">·</span>
              <SafeText text={s.predicate} className="font-mono text-[12px] text-ink-2" />
            </div>
            <SafeText text={s.evidence_text} as="p" className="mt-1.5 font-body text-[12.5px] leading-relaxed text-ink-2" />
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <CorroborationBadge level={s.corroboration_level} />
              <SensitivityBadge level={s.sensitivity} />
            </div>
            {b && (
              <div className="mt-2 font-mono text-[10.5px] tabular-nums text-ink-3">
                doc_strength {b.source_count} × {b.freshness_score} × ({b.trust_tier}+1) = <span className="text-ink-2">{b.computed_strength}</span>
              </div>
            )}
          </GlassCard>
        );
      })}
    </div>
  );
}
