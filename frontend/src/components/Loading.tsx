interface LoadingProps {
  message?: string;
}

export function Loading({ message = "Loading…" }: LoadingProps) {
  return (
    <div className="flex items-center justify-center gap-2 p-8">
      <span className="h-4 w-4 flex-none animate-spin rounded-full border-2 border-ink-3 border-t-transparent motion-reduce:animate-none" />
      <span className="font-mono text-[12px] text-ink-2">{message}</span>
    </div>
  );
}
