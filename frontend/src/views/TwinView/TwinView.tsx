import { useState } from "react";
import TwinChat from "./TwinChat";
import SourcePanel from "./SourcePanel";
import DisputePanel from "./DisputePanel";
import CoverageOverview from "./CoverageOverview";
import type { TwinResponse } from "../../hooks/useTwin";

const PROJECT_ID = 1;

export default function TwinView() {
  const [result, setResult] = useState<TwinResponse | null>(null);
  const hairline = { borderColor: "var(--card-hairline)" };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b" style={hairline}>
        <CoverageOverview projectId={PROJECT_ID} />
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="flex flex-1 flex-col border-r" style={hairline}>
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
