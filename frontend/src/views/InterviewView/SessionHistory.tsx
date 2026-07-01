import { useSessionList } from "../../hooks/useInterviews";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";
import { SafeText } from "../../components/SafeText";

interface SessionHistoryProps {
  projectId: number;
  onSelect: (sessionId: string) => void;
}

export function SessionHistory({ projectId, onSelect }: SessionHistoryProps) {
  const { data: sessions, isLoading, error } = useSessionList(projectId);

  if (isLoading) return <Loading />;
  if (error) return <p className="text-red-500 text-sm">Failed to load sessions</p>;
  if (!sessions?.length) return <EmptyState message="No interview sessions yet" />;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-700">Sessions</h3>
      {sessions.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className="w-full text-left p-3 bg-white rounded border hover:border-blue-400 transition-colors"
        >
          <div className="flex items-center justify-between">
            <SafeText text={s.topic} className="font-medium text-sm text-gray-800" />
            <span className={`text-xs px-2 py-0.5 rounded ${
              s.status === "completed" ? "bg-green-100 text-green-700" :
              s.status === "in_progress" ? "bg-blue-100 text-blue-700" :
              "bg-gray-100 text-gray-600"
            }`}>
              {s.status}
            </span>
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {s.claims_extracted ?? 0} claims
            {s.created_at && ` · ${new Date(s.created_at).toLocaleDateString()}`}
          </div>
        </button>
      ))}
    </div>
  );
}
