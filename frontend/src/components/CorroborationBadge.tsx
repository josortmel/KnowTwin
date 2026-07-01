const COLORS: Record<string, string> = {
  draft: "bg-gray-200 text-gray-600",
  single_source: "bg-blue-200 text-blue-800",
  corroborated: "bg-green-200 text-green-800",
  corroborated_by_employee: "bg-teal-200 text-teal-800",
  validated: "bg-amber-200 text-amber-800",
  rejected: "bg-red-200 text-red-800",
};

interface CorroborationBadgeProps {
  level: string;
  className?: string;
}

export function CorroborationBadge({ level, className = "" }: CorroborationBadgeProps) {
  const color = COLORS[level] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color} ${className}`}>
      {level.replace(/_/g, " ")}
    </span>
  );
}
