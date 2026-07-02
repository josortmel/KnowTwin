import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { DisputeBadge } from "../../components/DisputeBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import { TrustTierBadge } from "../../components/TrustTierBadge";
import { Button } from "../../components/Button";
import type { Claim } from "../../hooks/useClaims";

interface ClaimRowProps {
  claim: Claim;
  selected: boolean;
  onToggle: () => void;
  onApprove: () => void;
  onAudit: () => void;
  approving?: boolean;
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={15} height={15}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// The Setup workhorse (DESIGN.md §3 / §7). subject·predicate·object (mono meta),
// evidence (Hanken body via SafeText), the §7 badge vocabulary as dot+ink, a
// select checkbox, and a per-row force-approve. ALL user/agent text via SafeText.
export function ClaimRow({ claim, selected, onToggle, onApprove, onAudit, approving }: ClaimRowProps) {
  const canApprove = claim.corroboration_level !== "validated" && claim.corroboration_level !== "rejected";
  const object = claim.object_entity ?? claim.object_value ?? "";
  return (
    <GlassCard className="p-card-lg">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          aria-label={`Select claim ${claim.subject_entity} ${claim.predicate}`}
          className="mt-1 h-4 w-4 flex-none accent-accent"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            <SafeText text={claim.subject_entity} className="font-mono text-[12px] text-ink-1" />
            <span className="font-mono text-[11px] text-ink-3">·</span>
            <SafeText text={claim.predicate} className="font-mono text-[12px] text-ink-2" />
            {object && (
              <>
                <span className="font-mono text-[11px] text-ink-3">·</span>
                <SafeText text={object} className="font-mono text-[12px] text-ink-2" />
              </>
            )}
          </div>
          <SafeText text={claim.evidence_text} as="p" className="mt-1.5 font-body text-[13px] leading-relaxed text-ink-1" />
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <CorroborationBadge level={claim.corroboration_level} />
            <DisputeBadge state={claim.dispute_state} />
            <SensitivityBadge level={claim.sensitivity} />
            <TrustTierBadge tier={claim.trust_tier} />
          </div>
        </div>
        <div className="flex flex-none items-center gap-2">
          <button
            type="button"
            onClick={onAudit}
            aria-label="View audit trail"
            className="grid h-[30px] w-[30px] place-items-center rounded-md text-ink-3 transition-colors hover:text-ink-1"
            style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          >
            <ClockIcon />
          </button>
          {canApprove && (
            <Button variant="primary" onClick={onApprove} loading={approving} className="px-3 py-1.5 text-[12px]">
              Approve
            </Button>
          )}
        </div>
      </div>
    </GlassCard>
  );
}
