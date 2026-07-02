interface EmptyStateProps {
  message: string;
  icon?: string;
}

// Quiet centered message (DESIGN.md §3). No default emoji — the design stays
// instrument-like; pass `icon` only when it genuinely helps.
export function EmptyState({ message, icon }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
      {icon && <span className="text-2xl opacity-60">{icon}</span>}
      <span className="font-mono text-[12px] text-ink-3">{message}</span>
    </div>
  );
}
