import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { Chip } from "../../components/Chip";
import { DisputeBadge } from "../../components/DisputeBadge";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import type { DisputeGroup, TwinSource } from "../../hooks/useTwin";

function VersionCard({ v, n }: { v: TwinSource; n: number }) {
  const b = v.doc_strength_breakdown;
  const object = v.object_entity ?? v.object_value ?? "";
  return (
    <GlassCard className="p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">Version {n}</span>
        {v.source_type && <Chip>{v.source_type}</Chip>}
      </div>
      {object && <SafeText text={object} className="mt-1.5 block font-mono text-[12px] text-ink-1" />}
      <SafeText text={v.evidence_text} as="p" className="mt-1 font-body text-[12.5px] leading-relaxed text-ink-1" />
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <DisputeBadge state={v.dispute_state} />
        <CorroborationBadge level={v.corroboration_level} />
        <SensitivityBadge level={v.sensitivity} />
      </div>
      {b && (
        <div className="mt-2 font-mono text-[11px] tabular-nums text-ink-2">
          <span className="text-ink-3">doc_strength </span>
          {b.source_count} × {b.freshness_score} × ({b.trust_tier}+1) = <span className="text-ink-1">{b.computed_strength}</span>
        </div>
      )}
      {/* Deterministic resolution rationale — SafeText, never framed as LLM output. */}
      {v.why_resolved && (
        <SafeText text={v.why_resolved} as="p" className="mt-2 rounded-sm p-2 font-mono text-[11px] leading-relaxed text-ink-2" />
      )}
    </GlassCard>
  );
}

interface Props {
  disputes: DisputeGroup[];
}

// Twin disputes always show BOTH versions (DESIGN.md §7.3 — never silently pick).
export default function DisputePanel({ disputes }: Props) {
  if (disputes.length === 0) {
    return <div className="p-4 font-mono text-[12px] text-ink-3">No active disputes</div>;
  }

  return (
    <div className="space-y-4 p-4">
      <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Disputes ({disputes.length})</h3>
      {disputes.map((d, i) => (
        <div key={`${d.subject_entity}-${d.predicate}-${i}`}>
          <div className="mb-2 flex items-center gap-2">
            <DisputeBadge state="disputed" />
            <SafeText text={`${d.subject_entity} · ${d.predicate}`} className="font-body text-[13px] font-semibold text-ink-1" />
          </div>
          <div className="flex flex-col gap-2">
            {d.versions.map((v, vi) => (
              <VersionCard key={v.claim_id} v={v} n={vi + 1} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
