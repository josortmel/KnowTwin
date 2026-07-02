interface Props {
  projectId: number;
}

export function SttConfig({ projectId: _projectId }: Props) {
  return (
    <div className="space-y-2 font-mono text-[11px] text-ink-2">
      <div className="flex justify-between">
        <span className="text-ink-3">Language</span>
        <span className="text-ink-1">es (Spanish)</span>
      </div>
      <div className="flex justify-between">
        <span className="text-ink-3">Model</span>
        <span className="text-ink-1">small</span>
      </div>
      <p className="italic text-ink-3">STT config is managed via cell_task_configs (read-only in MVP).</p>
    </div>
  );
}
