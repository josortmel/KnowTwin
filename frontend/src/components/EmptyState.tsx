interface EmptyStateProps {
  message: string;
  icon?: string;
}

export function EmptyState({ message, icon = "📭" }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center p-8 text-gray-400">
      <span className="text-3xl mb-2">{icon}</span>
      <span className="text-sm">{message}</span>
    </div>
  );
}
