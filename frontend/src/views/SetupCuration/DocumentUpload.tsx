import { useRef, useState } from "react";
import { useDocuments, useUploadDocument } from "../../hooks/useDocuments";
import { useCuratorRun, type CuratorResult } from "../../hooks/useCurator";
import { SafeText } from "../../components/SafeText";
import { StateBadge } from "../../components/StateBadge";
import { Button } from "../../components/Button";
import { Panel, PanelState } from "../../components/Panel";
import { GlassCard } from "../../components/GlassCard";
import { pushToast } from "../../lib/toast";

const TRUST_HINTS = ["formal_contract", "adr", "signed_plan", "wiki", "presentation", "email", "orgchart", "other"];
const FIELD_STYLE = { background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" };

interface Props {
  projectId: number;
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function DocumentUpload({ projectId }: Props) {
  const { data: docs, isLoading, error } = useDocuments(projectId);
  const upload = useUploadDocument();
  const curator = useCuratorRun(projectId);
  const fileRef = useRef<HTMLInputElement>(null);
  const [trustHint, setTrustHint] = useState("");
  const [result, setResult] = useState<CuratorResult | null>(null);

  const indexing = (docs ?? []).some((d) => d.status !== "indexed" && d.status !== "failed");

  const handleUpload = () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    upload.mutate(
      { file, projectId, trustHint: trustHint || undefined },
      {
        onSuccess: () => {
          pushToast("Document uploaded — indexing…", { tone: "success" });
          if (fileRef.current) fileRef.current.value = "";
        },
        onError: (e) => pushToast(`Upload failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  const runCurator = () => {
    curator.mutate(undefined, {
      onSuccess: (r) => {
        setResult(r);
        pushToast(`Curator done — ${r.claims_created} claims created`, { tone: "success" });
      },
      onError: (e) => pushToast(`Curator failed: ${errMsg(e)}`, { tone: "error" }),
    });
  };

  return (
    <Panel
      title="Documents"
      tag={indexing ? "indexing…" : `${docs?.length ?? 0} docs`}
    >
      {/* 1. Upload with trust hint (bytes go through the main-process bridge). */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" className="font-mono text-[12px] text-ink-2" />
        <select
          value={trustHint}
          onChange={(e) => setTrustHint(e.target.value)}
          className="rounded-md px-2 py-1 font-mono text-[12px] text-ink-1 outline-none"
          style={FIELD_STYLE}
        >
          <option value="">Trust hint…</option>
          {TRUST_HINTS.map((h) => (
            <option key={h} value={h}>
              {h.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <Button variant="primary" onClick={handleUpload} loading={upload.isPending} className="px-3 py-1.5 text-[12px]">
          Upload
        </Button>
      </div>

      {/* 2. Document list with per-doc indexing status (polled). */}
      <PanelState loading={isLoading} error={!!error} empty={!!docs && docs.length === 0} emptyLabel="No documents uploaded">
        {docs && docs.length > 0 && (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b text-left font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3" style={{ borderColor: "var(--card-hairline)" }}>
                <th className="py-1 font-normal">Filename</th>
                <th className="font-normal">Type</th>
                <th className="font-normal">Status</th>
                <th className="font-normal">Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-b" style={{ borderColor: "var(--card-hairline)" }}>
                  <td className="py-1 text-ink-1">
                    <SafeText text={d.filename} />
                  </td>
                  <td className="text-ink-2">
                    <SafeText text={d.doc_type} />
                  </td>
                  <td>
                    {d.status === "indexed" || d.status === "failed" ? (
                      <StateBadge state={d.status} />
                    ) : (
                      <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-ink-2">
                        <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-3 border-t-transparent motion-reduce:animate-none" />
                        {d.status}
                      </span>
                    )}
                  </td>
                  <td className="font-mono text-[10px] text-ink-3">{new Date(d.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </PanelState>

      {/* 3–5. Trigger curator (synchronous) → show the extracted-claims result. */}
      <div className="mt-4 flex items-center gap-3 border-t pt-3" style={{ borderColor: "var(--card-hairline)" }}>
        <Button variant="default" onClick={runCurator} loading={curator.isPending} disabled={indexing || !docs?.length}>
          Run curator
        </Button>
        {indexing && <span className="font-mono text-[10px] text-ink-3">waiting for indexing…</span>}
      </div>

      {result && (
        <GlassCard className="mt-3 p-card-lg">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">Curator run</div>
          <div className="flex flex-wrap gap-x-6 gap-y-1.5 font-mono text-[12px] text-ink-2">
            <span>
              <span className="tabular-nums text-ink-1">{result.claims_created}</span> claims created
            </span>
            <span>
              <span className="tabular-nums text-ink-1">{result.claims_promoted}</span> promoted
            </span>
            <span>
              <span className="tabular-nums text-ink-1">{result.contradictions_found}</span> contradictions
            </span>
            <span>
              <span className="tabular-nums text-ink-1">{result.gaps_found}</span> gaps
            </span>
          </div>
          <p className="mt-2 font-body text-[12px] text-ink-3">Review new claims in the Curation Inbox tab.</p>
        </GlassCard>
      )}
    </Panel>
  );
}
