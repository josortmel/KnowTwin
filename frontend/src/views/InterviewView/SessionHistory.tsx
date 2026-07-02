import { useSessionList } from "../../hooks/useInterviews";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";
import { SafeText } from "../../components/SafeText";
import { GlassCard } from "../../components/GlassCard";
import { StateBadge } from "../../components/StateBadge";

interface SessionHistoryProps {
  projectId: number;
  onSelect: (sessionId: string) => void;
}

export function SessionHistory({ projectId, onSelect }: SessionHistoryProps) {
  const { data: sessions, isLoading, error } = useSessionList(projectId);

  if (isLoading) return <Loading message="Loading sessions…" />;
  if (error) return <p className="font-mono text-[12px] text-ink-2">Failed to load sessions</p>;
  if (!sessions?.length) return <EmptyState message="No interview sessions yet" />;

  return (
    <div className="space-y-2">
      <h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Sessions</h3>
      {sessions.map((s) => (
        <button key={s.id} onClick={() => onSelect(s.id)} className="w-full text-left">
          <GlassCard className="p-3 transition-transform hover:-translate-y-0.5">
            <div className="flex items-center justify-between gap-2">
              <SafeText text={s.topic} className="font-body text-[13px] font-medium text-ink-1" />
              <StateBadge state={s.status} />
            </div>
            <div className="mt-1 font-mono text-[10px] text-ink-3">
              {s.claims_extracted ?? 0} claims
              {s.created_at && ` · ${new Date(s.created_at).toLocaleDateString()}`}
            </div>
          </GlassCard>
        </button>
      ))}
    </div>
  );
}
