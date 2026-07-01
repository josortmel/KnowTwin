import { SafeText } from "../../components/SafeText";

interface TopicIndicatorProps {
  topic: string | null;
  converged: boolean;
}

export function TopicIndicator({ topic, converged }: TopicIndicatorProps) {
  if (!topic) return null;
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-blue-50 rounded">
      <span className="text-sm text-gray-500">Current topic:</span>
      <SafeText text={topic} className="font-medium text-blue-800" />
      {converged && (
        <span className="inline-block px-2 py-0.5 bg-green-200 text-green-800 rounded text-xs font-medium">
          converged
        </span>
      )}
    </div>
  );
}
