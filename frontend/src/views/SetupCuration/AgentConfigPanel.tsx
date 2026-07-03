import { useState } from "react";
import { useCellConfigs, useCreateCellConfig, useUpdateCellConfig, useResetCellConfig, useCellTemplates, useUpdateTemplate, type CellConfig, type PromptTemplate } from "../../hooks/useCellConfigs";
import { useProviders, useCreateProvider, useDeleteProvider, useProviderModels, type Provider } from "../../hooks/useProviders";
import { SafeText } from "../../components/SafeText";
import { Loading } from "../../components/Loading";
import { Button } from "../../components/Button";
import { Dot } from "../../components/Dot";
import { pushToast } from "../../lib/toast";

// All 4 metacognition cells belong to the "default" agent (Hilo-confirmed).
const CELL_AGENT = "default";
const CELLS: { type: string; label: string; hint: string }[] = [
  { type: "curator_pre", label: "Curator (pre)", hint: "Extracts claims from raw interview turns." },
  { type: "curator_post", label: "Curator (post)", hint: "Consolidates and de-duplicates claims after a session." },
  { type: "verifier", label: "Verifier", hint: "Checks claims for contradictions against the graph." },
  { type: "interviewer", label: "Interviewer", hint: "Drives the interview — picks topics and follow-ups." },
];

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

function ProviderRow({ p, onDelete, deleting }: { p: Provider; onDelete: () => void; deleting: boolean }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="flex items-center gap-3 rounded-md px-3 py-2.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <Dot s="ok" size={5} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <SafeText text={p.display_name || p.provider} className="font-mono text-[12.5px] text-ink-1" />
          {p.display_name && <SafeText text={p.provider} className="font-mono text-[10px] text-ink-3" />}
        </div>
        <div className="mt-0.5 font-mono text-[10.5px] text-ink-3">
          <SafeText text={p.api_key_masked} />
          {p.model_default && <> · default <SafeText text={p.model_default} /></>}
        </div>
      </div>
      {/* 2-step confirm: deleting a provider breaks any cell config that uses it. */}
      {confirm ? (
        <div className="flex flex-none items-center gap-1.5">
          <span className="font-mono text-[10px] text-ink-3">Delete?</span>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            aria-label={`Confirm delete provider ${p.provider}`}
            className="rounded-md px-2 py-1 font-mono text-[10.5px] text-ink-1 transition-colors disabled:opacity-40"
            style={{ background: "color-mix(in srgb, var(--red) 16%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 45%, transparent)" }}
          >
            Yes
          </button>
          <button type="button" onClick={() => setConfirm(false)} className="rounded-md px-2 py-1 font-mono text-[10.5px] text-ink-2 transition-colors hover:text-ink-1" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
            No
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirm(true)}
          disabled={deleting}
          aria-label={`Delete provider ${p.provider}`}
          className="flex-none rounded-md px-2 py-1 font-mono text-[10.5px] text-ink-3 transition-colors hover:text-ink-1 disabled:opacity-40"
          style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
        >
          Delete
        </button>
      )}
    </div>
  );
}

function AddProviderForm() {
  const create = useCreateProvider();
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelDefault, setModelDefault] = useState("");
  const [show, setShow] = useState(false);

  // Backend pattern for the provider slug: ^[a-z0-9_]+$.
  const slug = provider.trim().toLowerCase();
  const slugValid = /^[a-z0-9_]+$/.test(slug);
  const canAdd = slugValid && apiKey.trim().length > 0 && !create.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canAdd) return;
    create.mutate(
      { provider: slug, api_key: apiKey.trim(), ...(modelDefault.trim() ? { model_default: modelDefault.trim() } : {}) },
      {
        onSuccess: () => {
          pushToast(`Provider ${slug} added`, { tone: "success" });
          setProvider("");
          setApiKey("");
          setModelDefault("");
        },
        onError: (e) => pushToast(`Add failed: ${errMsg(e)}`, { tone: "error" }),
      },
    );
  };

  const field = { background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } as const;
  return (
    <form onSubmit={submit} className="mt-2 flex flex-col gap-2 rounded-md p-3" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <input
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            placeholder="Provider (e.g. deepseek)"
            aria-invalid={!!provider.trim() && !slugValid}
            className="w-full rounded-md px-2.5 py-2 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
            style={provider.trim() && !slugValid ? { ...field, boxShadow: "inset 0 0 0 1px var(--red)" } : field}
          />
          {provider.trim() && !slugValid && <div className="mt-1 font-mono text-[10px] text-ink-3">Lowercase letters, digits and underscores only.</div>}
        </div>
        <div className="flex gap-1.5">
          <input
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            type={show ? "text" : "password"}
            placeholder="API key"
            autoComplete="off"
            className="min-w-0 flex-1 rounded-md px-2.5 py-2 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
            style={field}
          />
          <button type="button" onClick={() => setShow((s) => !s)} className="flex-none rounded-md px-2 py-2 font-mono text-[10.5px] text-ink-2 transition-colors hover:text-ink-1" style={field}>
            {show ? "Hide" : "Show"}
          </button>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <input
          value={modelDefault}
          onChange={(e) => setModelDefault(e.target.value)}
          placeholder="Default model (optional)"
          className="min-w-0 flex-1 rounded-md px-2.5 py-2 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3"
          style={field}
        />
        <Button type="submit" variant="primary" disabled={!canAdd} loading={create.isPending} className="flex-none px-4 py-2 text-[12px]">
          Add provider
        </Button>
      </div>
    </form>
  );
}

// One agent cell = full config: provider + model + params + its system prompt.
function CellCard({ cell, config, providers, template }: { cell: (typeof CELLS)[number]; config?: CellConfig; providers: Provider[]; template?: PromptTemplate }) {
  const createCfg = useCreateCellConfig();
  const updateCfg = useUpdateCellConfig();
  const resetCfg = useResetCellConfig();
  const updateTpl = useUpdateTemplate();
  const [provider, setProvider] = useState(config?.provider ?? "");
  const [model, setModel] = useState(config?.model ?? "");
  const models = useProviderModels(provider || null);

  const cfg = (config?.config ?? {}) as Record<string, unknown>;
  const numOrEmpty = (v: unknown) => (typeof v === "number" ? String(v) : "");
  const [temperature, setTemperature] = useState(numOrEmpty(cfg.temperature));
  const [maxTokens, setMaxTokens] = useState(numOrEmpty(cfg.max_tokens));
  const [prompt, setPrompt] = useState(template?.content ?? "");

  const saving = createCfg.isPending || updateCfg.isPending;
  const dirty = provider !== (config?.provider ?? "") || model !== (config?.model ?? "");
  const canSave = !!provider && !!model && dirty && !saving;

  const paramsDirty = temperature !== numOrEmpty(cfg.temperature) || maxTokens !== numOrEmpty(cfg.max_tokens);
  const onSaveParams = () => {
    if (!config) return;
    const next: Record<string, unknown> = { ...cfg };
    if (temperature.trim() === "") delete next.temperature; else next.temperature = Number(temperature);
    if (maxTokens.trim() === "") delete next.max_tokens; else next.max_tokens = Number(maxTokens);
    updateCfg.mutate(
      { id: config.id, body: { config: next } },
      { onSuccess: () => pushToast(`${cell.label} params saved`, { tone: "success" }), onError: (e) => pushToast(`Save failed: ${errMsg(e)}`, { tone: "error" }) },
    );
  };

  const promptDirty = prompt !== (template?.content ?? "");
  const onSavePrompt = () => {
    if (!template) return;
    updateTpl.mutate(
      { id: template.id, body: { content: prompt } },
      { onSuccess: () => pushToast(`${cell.label} prompt saved`, { tone: "success" }), onError: (e) => pushToast(`Save failed: ${errMsg(e)}`, { tone: "error" }) },
    );
  };

  const onReset = () => {
    if (!config) return;
    resetCfg.mutate(config.id, {
      onSuccess: () => pushToast(`${cell.label} reset to defaults`, { tone: "success" }),
      onError: (e) => pushToast(`Reset failed: ${errMsg(e)}`, { tone: "error" }),
    });
  };

  const onSave = () => {
    const done = (msg: string) => pushToast(msg, { tone: "success" });
    const fail = (e: unknown) => pushToast(`Save failed: ${errMsg(e)}`, { tone: "error" });
    if (config) {
      updateCfg.mutate({ id: config.id, body: { provider, model } }, { onSuccess: () => done(`${cell.label} updated`), onError: fail });
    } else {
      createCfg.mutate({ agent_identifier: CELL_AGENT, cell_type: cell.type, provider, model }, { onSuccess: () => done(`${cell.label} configured`), onError: fail });
    }
  };

  // Switching provider invalidates a model that doesn't belong to it.
  const onPickProvider = (next: string) => {
    setProvider(next);
    setModel("");
  };

  const field = { background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } as const;
  return (
    <div className="flex flex-col gap-2.5 rounded-md p-3" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[12.5px] text-ink-1">{cell.label}</span>
            {config && <Dot s="ok" size={4} />}
          </div>
          <div className="mt-0.5 text-[11px] leading-snug text-ink-3">{cell.hint}</div>
        </div>
        {config && (
          <button type="button" onClick={onReset} disabled={resetCfg.isPending} className="flex-none rounded-md px-2 py-1 font-mono text-[10px] text-ink-3 transition-colors hover:text-ink-1 disabled:opacity-40" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
            Reset
          </button>
        )}
      </div>
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">Provider</span>
        <select value={provider} onChange={(e) => onPickProvider(e.target.value)} className="rounded-md px-2 py-1.5 font-mono text-[12px] text-ink-1 outline-none" style={field}>
          <option value="">Select provider…</option>
          {providers.map((p) => (
            <option key={p.id} value={p.provider}>{p.display_name || p.provider}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">Model</span>
        <select value={model} onChange={(e) => setModel(e.target.value)} disabled={!provider || models.isPending} className="rounded-md px-2 py-1.5 font-mono text-[12px] text-ink-1 outline-none disabled:opacity-50" style={field}>
          <option value="">{!provider ? "Pick a provider first" : models.isPending ? "Loading models…" : "Select model…"}</option>
          {models.data?.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </label>
      <Button variant="primary" onClick={onSave} disabled={!canSave} loading={saving} className="py-2 text-[12px]">
        {config ? "Save" : "Configure"}
      </Button>

      {/* Inference params + system prompt — only once the cell has a saved config. */}
      {config && (
        <>
          <div className="mt-1 border-t pt-2.5" style={{ borderColor: "var(--card-hairline)" }}>
            <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-3">Parameters</div>
            <div className="flex gap-2">
              <label className="flex flex-1 flex-col gap-1">
                <span className="font-mono text-[9px] uppercase tracking-[0.06em] text-ink-3">Temperature</span>
                <input value={temperature} onChange={(e) => setTemperature(e.target.value.replace(/[^0-9.]/g, ""))} inputMode="decimal" placeholder="—" className="rounded-md px-2 py-1.5 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3" style={field} />
              </label>
              <label className="flex flex-1 flex-col gap-1">
                <span className="font-mono text-[9px] uppercase tracking-[0.06em] text-ink-3">Max tokens</span>
                <input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value.replace(/\D/g, ""))} inputMode="numeric" placeholder="—" className="rounded-md px-2 py-1.5 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-3" style={field} />
              </label>
            </div>
            <Button variant="default" onClick={onSaveParams} disabled={!paramsDirty || saving} className="mt-2 w-full py-1.5 text-[11.5px]">
              Save params
            </Button>
          </div>

          <div className="mt-1 border-t pt-2.5" style={{ borderColor: "var(--card-hairline)" }}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-3">System prompt</span>
              {template?.is_default && <span className="rounded-full px-1.5 py-0.5 font-mono text-[8.5px] uppercase tracking-[0.06em] text-ink-3" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>Default prompt</span>}
            </div>
            {template ? (
              <>
                <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={5} className="w-full resize-y rounded-md px-2.5 py-2 font-mono text-[11px] leading-relaxed text-ink-1 outline-none" style={field} />
                <Button variant="default" onClick={onSavePrompt} disabled={!promptDirty || updateTpl.isPending} loading={updateTpl.isPending} className="mt-2 w-full py-1.5 text-[11.5px]">
                  Save prompt
                </Button>
              </>
            ) : (
              <div className="font-mono text-[10.5px] text-ink-3">No prompt template linked to this cell.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function AgentConfigPanel() {
  const { data: providers, isLoading: providersLoading } = useProviders();
  const { data: configs, isLoading: configsLoading } = useCellConfigs();
  const { data: templates, isLoading: templatesLoading } = useCellTemplates();
  const deleteProvider = useDeleteProvider();

  const onDelete = (p: Provider) =>
    deleteProvider.mutate(p.id, {
      onSuccess: () => pushToast(`Provider ${p.provider} removed`, { tone: "success" }),
      onError: (e) => pushToast(`Delete failed: ${errMsg(e)}`, { tone: "error" }),
    });

  const noProviders = !providersLoading && (providers?.length ?? 0) === 0;
  const configByType = new Map((configs ?? []).map((c) => [c.cell_type, c]));
  const templateById = new Map((templates ?? []).map((t) => [t.id, t]));

  return (
    <div className="rounded border p-4" style={{ borderColor: "var(--card-hairline)" }}>
      <h3 className="mb-1 font-semibold">Agent Configuration</h3>
      <p className="mb-4 text-[12px] leading-relaxed text-ink-3">
        Register an LLM provider, then assign a provider, model, and system prompt to each agent cell. This is what powers interviews, twin queries, and curator extraction — no environment variables required.
      </p>

      <h4 className="mb-2 text-sm font-medium text-ink-2">LLM Providers</h4>
      {providersLoading && <Loading />}
      {noProviders && (
        <div className="rounded-md p-3.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
          <div className="text-[13px] text-ink-1">No LLM providers configured.</div>
          <div className="mt-1 text-[12px] leading-relaxed text-ink-3">Add a provider below to enable AI-powered features.</div>
        </div>
      )}
      {providers && providers.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {providers.map((p) => (
            <ProviderRow key={p.id} p={p} onDelete={() => onDelete(p)} deleting={deleteProvider.isPending} />
          ))}
        </div>
      )}
      <AddProviderForm />

      <h4 className="mb-2 mt-6 text-sm font-medium text-ink-2">Agent Cells</h4>
      {configsLoading || templatesLoading ? (
        <Loading />
      ) : noProviders ? (
        <div className="rounded-md p-3.5 text-[12px] leading-relaxed text-ink-3" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
          Add a provider first — then you can assign a model to each cell.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {CELLS.map((cell) => {
            const config = configByType.get(cell.type);
            const template = config?.prompt_template_id ? templateById.get(config.prompt_template_id) : undefined;
            return (
              <CellCard
                key={`${cell.type}:${config?.id ?? "new"}:${config?.updated_at ?? ""}:${template?.updated_at ?? ""}`}
                cell={cell}
                config={config}
                providers={providers ?? []}
                template={template}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
