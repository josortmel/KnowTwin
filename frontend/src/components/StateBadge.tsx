const COLORS: Record<string, string> = {
  unknown: "bg-gray-200 text-gray-700",
  partial: "bg-yellow-200 text-yellow-800",
  clear: "bg-green-200 text-green-800",
  disputed: "bg-red-200 text-red-800",
  stale: "bg-orange-200 text-orange-800",
  validated: "bg-emerald-200 text-emerald-800",
};

interface StateBadgeProps {
  state: string;
  className?: string;
}

export function StateBadge({ state, className = "" }: StateBadgeProps) {
  const color = COLORS[state] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color} ${className}`}>
      {state}
    </span>
  );
}
