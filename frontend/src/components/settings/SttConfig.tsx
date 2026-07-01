interface Props {
  projectId: number;
}

export function SttConfig({ projectId: _projectId }: Props) {
  return (
    <div>
      <h3 className="text-sm font-semibold mb-2">STT Configuration</h3>
      <div className="space-y-2 text-xs text-gray-600">
        <div className="flex justify-between">
          <span>Language</span>
          <span className="font-mono">es (Spanish)</span>
        </div>
        <div className="flex justify-between">
          <span>Model</span>
          <span className="font-mono">small</span>
        </div>
        <p className="text-gray-400 italic">
          STT config is managed via cell_task_configs (read-only in MVP).
        </p>
      </div>
    </div>
  );
}
