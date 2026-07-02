import { useState } from "react";
import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { Chip } from "../../components/Chip";
import { Button } from "../../components/Button";
import { DisputeBadge } from "../../components/DisputeBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import type { Dispute, DisputeSide } from "../../hooks/useDisputes";
import type { ProjectMember } from "../../hooks/useProjectMembers";

function SideCard({ side, label }: { side: DisputeSide | null; label: string }) {
  if (!side) {
    return (
      <GlassCard className="p-card-lg">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">{label}</span>
        <p className="mt-2 font-mono text-[12px] text-ink-3">No counterpart</p>
      </GlassCard>
    );
  }
  const b = side.doc_strength_breakdown;
  const object = side.object_entity ?? side.object_value ?? "";
  return (
    <GlassCard className="p-card-lg">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">{label}</span>
        <Chip>{side.source_type}</Chip>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1">
        <SafeText text={side.subject_entity} className="font-mono text-[12px] text-ink-1" />
        <span className="font-mono text-[11px] text-ink-3">·</span>
        <SafeText text={side.predicate} className="font-mono text-[12px] text-ink-2" />
        {object && (
          <>
            <span className="font-mono text-[11px] text-ink-3">·</span>
            <SafeText text={object} className="font-mono text-[12px] text-ink-1" />
          </>
        )}
      </div>
      {/* Deterministic evidence text — SafeText, never framed as LLM output. */}
      <SafeText text={side.evidence_text} as="p" className="mt-1.5 font-body text-[13px] leading-relaxed text-ink-1" />
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <DisputeBadge state={side.dispute_state} />
        <CorroborationBadge level={side.corroboration_level} />
        <SensitivityBadge level={side.sensitivity} />
      </div>
      {b && (
        <div className="mt-2 font-mono text-[11px] tabular-nums text-ink-2">
          <span className="text-ink-3">doc_strength </span>
          {b.source_count} × {b.freshness_score} × ({b.trust_tier}+1) = <span className="text-ink-1">{b.computed_strength}</span>
        </div>
      )}
    </GlassCard>
  );
}

interface DisputePairProps {
  dispute: Dispute;
  onResolve: (dispute: Dispute) => void;
  onAssign: (claimId: string, resolverUserId: number) => void;
  assigning?: boolean;
  members?: ProjectMember[];
}

// A dispute shown as both versions side-by-side (DESIGN.md §7.3 — never silently
// pick a winner). Resolve opens the note dialog; assign routes it to a resolver.
export function DisputePair({ dispute, onResolve, onAssign, assigning, members }: DisputePairProps) {
  const { claim, counterpart } = dispute;
  const [resolverId, setResolverId] = useState("");

  return (
    <div className="border-b border-[color:var(--card-hairline)] pb-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <DisputeBadge state="disputed" />
          <SafeText text={claim.subject_entity} className="font-body text-[14px] font-semibold text-ink-1" />
          <span className="font-mono text-[10px] tabular-nums text-ink-3">crit {claim.criticality}</span>
        </div>
        <Button variant="primary" onClick={() => onResolve(dispute)} className="px-3 py-1.5 text-[12px]">
          Resolve
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <SideCard side={claim} label="Claim" />
        <SideCard side={counterpart} label="Counterpart" />
      </div>

      {/* Assign resolver — dropdown fed by GET /projects/{pid}/members. */}
      <div className="mt-3 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Assign resolver</span>
        <select
          value={resolverId}
          onChange={(e) => setResolverId(e.target.value)}
          className="rounded-sm px-2 py-1 font-mono text-[12px] text-ink-1 outline-none"
          style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
        >
          <option value="">Select…</option>
          {members?.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.name} ({m.role})
            </option>
          ))}
        </select>
        <Button
          variant="default"
          disabled={!resolverId || assigning}
          onClick={() => onAssign(claim.claim_id, Number(resolverId))}
          className="px-3 py-1.5 text-[12px]"
        >
          Assign
        </Button>
      </div>
    </div>
  );
}
