import { useRef, useState } from "react";
import { useDocuments, useUploadDocument } from "../../hooks/useDocuments";
import { SafeText } from "../../components/SafeText";
import { StateBadge } from "../../components/StateBadge";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";

const TRUST_HINTS = ["formal_contract", "adr", "signed_plan", "wiki", "presentation", "email", "orgchart", "other"];

interface Props { projectId: number }

export function DocumentUpload({ projectId }: Props) {
  const { data: docs, isLoading, error } = useDocuments(projectId);
  const upload = useUploadDocument();
  const fileRef = useRef<HTMLInputElement>(null);
  const [trustHint, setTrustHint] = useState("");

  const handleUpload = () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    upload.mutate({ file, projectId, trustHint: trustHint || undefined });
  };

  return (
    <div className="border rounded p-4">
      <h3 className="font-semibold mb-3">Documents</h3>
      <div className="flex gap-2 mb-3">
        <input ref={fileRef} type="file" className="text-sm" />
        <select value={trustHint} onChange={e => setTrustHint(e.target.value)}
          className="border rounded px-2 py-1 text-sm">
          <option value="">Trust hint...</option>
          {TRUST_HINTS.map(h => <option key={h} value={h}>{h.replace(/_/g, " ")}</option>)}
        </select>
        <button onClick={handleUpload} disabled={upload.isPending}
          className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
          Upload
        </button>
      </div>
      {upload.isError && <p className="text-red-500 text-xs mb-2">{String(upload.error)}</p>}
      {isLoading && <Loading />}
      {error && <p className="text-red-500 text-sm">{String(error)}</p>}
      {docs && docs.length === 0 && <EmptyState message="No documents uploaded" />}
      {docs && docs.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-gray-500 border-b">
            <th className="py-1">Filename</th><th>Type</th><th>Status</th><th>Uploaded</th>
          </tr></thead>
          <tbody>
            {docs.map(d => (
              <tr key={d.id} className="border-b">
                <td className="py-1"><SafeText text={d.filename} /></td>
                <td><SafeText text={d.doc_type} /></td>
                <td><StateBadge state={d.status} /></td>
                <td className="text-gray-400 text-xs">{new Date(d.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
