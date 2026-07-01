import { useState } from 'react';
import TwinChat from './TwinChat';
import SourcePanel from './SourcePanel';
import DisputePanel from './DisputePanel';
import CoverageOverview from './CoverageOverview';
import type { TwinResponse } from '../../hooks/useTwin';

const PROJECT_ID = 1;

export default function TwinView() {
  const [result, setResult] = useState<TwinResponse | null>(null);

  return (
    <div className="flex flex-col h-full">
      <CoverageOverview projectId={PROJECT_ID} />
      <div className="flex flex-1 min-h-0 border-t">
        <div className="flex-1 flex flex-col border-r">
          <TwinChat projectId={PROJECT_ID} onResult={setResult} />
        </div>
        <div className="w-96 overflow-y-auto">
          <SourcePanel sources={result?.sources ?? []} />
          <DisputePanel disputes={result?.disputes ?? []} />
        </div>
      </div>
    </div>
  );
}
