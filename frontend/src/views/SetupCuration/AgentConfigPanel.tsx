import { useState } from "react";
import { useCellConfigs } from "../../hooks/useCellConfigs";
import { useProviders, useSetProviderKey } from "../../hooks/useProviders";
import { SafeText } from "../../components/SafeText";
import { Loading } from "../../components/Loading";
import { EmptyState } from "../../components/EmptyState";
import { Button } from "../../components/Button";
import { Dot } from "../../components/Dot";

export function AgentConfigPanel() {
  const { data: configs, isLoading: configsLoading } = useCellConfigs();
  const { data: providers, isLoading: providersLoading } = useProviders();
  const setKey = useSetProviderKey();
  const [newProvider, setNewProvider] = useState("");
  const [newKey, setNewKey] = useState("");

  const handleSetKey = () => {
    if (!newProvider || !newKey) return;
    setKey.mutate({ provider: newProvider, apiKey: newKey });
    setNewKey("");
  };

  return (
    <div className="border rounded p-4">
      <h3 className="font-semibold mb-3">Agent Configuration</h3>

      <h4 className="text-sm font-medium text-ink-3 mb-2">Cell Configs</h4>
      {configsLoading && <Loading />}
      {configs && configs.length === 0 && <EmptyState message="No cell configs" />}
      {configs && configs.length > 0 && (
        <table className="w-full text-sm mb-4">
          <thead><tr className="text-left text-ink-3 border-b">
            <th className="py-1">Type</th><th>Model</th><th>Provider</th><th>Enabled</th>
          </tr></thead>
          <tbody>
            {configs.map(c => (
              <tr key={c.id} className="border-b">
                <td className="py-1"><SafeText text={c.cell_type} /></td>
                <td><SafeText text={c.model ?? "default"} /></td>
                <td><SafeText text={c.provider ?? "default"} /></td>
                <td>{c.enabled ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4 className="text-sm font-medium text-ink-3 mb-2">LLM Providers</h4>
      {providersLoading && <Loading />}
      {providers && (
        <div className="space-y-1 mb-3">
          {providers.map(p => (
            <div key={p.provider} className="flex items-center gap-2 text-sm">
              <SafeText text={p.provider} />
              <span className="inline-flex items-center gap-1.5 text-ink-2">
                <Dot s={p.has_key ? "ok" : "idle"} size={5} />
                {p.has_key ? "Key configured" : "No key"}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <input value={newProvider} onChange={e => setNewProvider(e.target.value)}
          placeholder="Provider name" className="rounded-md px-2 py-1 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
          style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }} />
        <input value={newKey} onChange={e => setNewKey(e.target.value)} type="password"
          placeholder="API key" className="rounded-md px-2 py-1 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
          style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }} />
        <Button variant="primary" onClick={handleSetKey} loading={setKey.isPending} className="px-3 py-1.5 text-[12px]">
          Set Key
        </Button>
      </div>
    </div>
  );
}
