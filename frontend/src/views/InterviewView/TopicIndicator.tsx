import { SafeText } from "../../components/SafeText";
import { Dot } from "../../components/Dot";

interface TopicIndicatorProps {
  topic: string | null;
  converged: boolean;
}

export function TopicIndicator({ topic, converged }: TopicIndicatorProps) {
  if (!topic) return null;
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Topic</span>
      <SafeText text={topic} className="font-body text-[13px] font-medium text-ink-1" />
      {converged && (
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-ink-2">
          <Dot s="ok" size={5} />
          converged
        </span>
      )}
    </div>
  );
}
