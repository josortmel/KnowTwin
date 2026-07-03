import { useEffect, useMemo, useRef, useState } from "react";
import { SafeText } from "../../components/SafeText";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { Dot } from "../../components/Dot";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import { DisputeBadge } from "../../components/DisputeBadge";
import CoverageOverview from "./CoverageOverview";
import { useProjectMembers, type ProjectMember } from "../../hooks/useProjectMembers";
import { useTwinQuery, type TwinSource, type DisputeGroup } from "../../hooks/useTwin";

const PROJECT_ID = 1;

interface Turn {
  id: number;
  question: string;
  status: "pending" | "done" | "error";
  answer?: string;
  sources: TwinSource[];
  disputes: DisputeGroup[];
  error?: string;
}

// A single cited source line (inside the collapsible "Sources" section).
function SourceLine({ s, n }: { s: TwinSource; n: number }) {
  const object = s.object_entity ?? s.object_value ?? "";
  return (
    <div className="rounded-md p-2.5" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
        <span className="font-mono text-[10.5px] text-ink-3">[{n}]</span>
        <SafeText text={s.subject_entity} className="font-mono text-[11.5px] text-ink-1" />
        <span className="font-mono text-[10.5px] text-ink-3">·</span>
        <SafeText text={s.predicate} className="font-mono text-[11.5px] text-ink-2" />
        {object && (
          <>
            <span className="font-mono text-[10.5px] text-ink-3">·</span>
            <SafeText text={object} className="font-mono text-[11.5px] text-ink-2" />
          </>
        )}
      </div>
      <SafeText text={s.evidence_text} as="p" className="mt-1.5 font-body text-[12px] leading-relaxed text-ink-2" />
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <CorroborationBadge level={s.corroboration_level} />
        <SensitivityBadge level={s.sensitivity} />
      </div>
    </div>
  );
}

// A dispute group is "active" while any version is still in the disputed state;
// once curated, versions carry a resolved_* state.
function isActiveDispute(d: DisputeGroup): boolean {
  return d.versions.some((v) => v.dispute_state === "disputed");
}
function disputeGroupState(d: DisputeGroup): string {
  if (isActiveDispute(d)) return "disputed";
  return d.versions.find((v) => v.dispute_state?.startsWith("resolved"))?.dispute_state ?? "resolved_in_favor";
}

// Disputed fact — both versions, never silently resolved (§7.3). Resolved groups
// render dimmed with their resolution badge.
function DisputeBlock({ d, resolved }: { d: DisputeGroup; resolved?: boolean }) {
  return (
    <div className="rounded-md p-3" style={{ opacity: resolved ? 0.65 : 1, background: "color-mix(in srgb, var(--red) 7%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 22%, transparent)" }}>
      <div className="mb-2 flex items-center gap-2">
        <DisputeBadge state={disputeGroupState(d)} />
        <SafeText text={`${d.subject_entity} · ${d.predicate}`} className="font-body text-[12.5px] font-semibold text-ink-1" />
      </div>
      <div className="flex flex-col gap-2">
        {d.versions.map((v, vi) => {
          const object = v.object_entity ?? v.object_value ?? "";
          return (
            <div key={v.claim_id} className="rounded-md p-2.5" style={{ background: "var(--card-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
              <div className="flex items-center justify-between">
                <span className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-3">Version {vi + 1}</span>
                {v.source_type && <span className="font-mono text-[9.5px] text-ink-3"><SafeText text={v.source_type} /></span>}
              </div>
              {object && <SafeText text={object} className="mt-1 block font-mono text-[11.5px] text-ink-1" />}
              <SafeText text={v.evidence_text} as="p" className="mt-1 font-body text-[12px] leading-relaxed text-ink-1" />
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <CorroborationBadge level={v.corroboration_level} />
                <SensitivityBadge level={v.sensitivity} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Twin's answer bubble: natural-language answer up top, sources collapsed below.
function TwinBubble({ turn }: { turn: Turn }) {
  const [showSources, setShowSources] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const activeDisputes = turn.disputes.filter(isActiveDispute);
  const resolvedDisputes = turn.disputes.filter((d) => !isActiveDispute(d));
  const shownDisputes = showResolved ? [...activeDisputes, ...resolvedDisputes] : activeDisputes;
  return (
    <div className="flex justify-start">
      <GlassCard className="max-w-[85%] p-3.5">
        {turn.status === "pending" ? (
          <div className="flex items-center gap-2 font-mono text-[12px] text-ink-3">
            <span className="h-[6px] w-[6px] animate-pulse rounded-full motion-reduce:animate-none" style={{ background: "var(--accent)" }} />
            Thinking…
          </div>
        ) : turn.status === "error" ? (
          <div className="flex items-center gap-2">
            <Dot s="alert" glow />
            <SafeText text={turn.error || "Query failed"} className="font-mono text-[12px] text-ink-2" />
          </div>
        ) : (
          <>
            <SafeText text={turn.answer || ""} as="div" className="whitespace-pre-wrap font-body text-[13.5px] leading-relaxed text-ink-1" />

            {turn.disputes.length > 0 && (
              <div className="mt-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">
                    Disputed{activeDisputes.length > 0 ? ` (${activeDisputes.length})` : ""}
                  </span>
                  {resolvedDisputes.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setShowResolved((s) => !s)}
                      aria-pressed={showResolved}
                      className="rounded-full px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] transition-colors"
                      style={showResolved
                        ? { color: "var(--ink-1)", background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }
                        : { color: "var(--ink-3)", background: "transparent", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
                    >
                      {showResolved ? "Hide" : "Show"} resolved ({resolvedDisputes.length})
                    </button>
                  )}
                </div>
                {shownDisputes.length === 0 ? (
                  <div className="font-mono text-[10.5px] text-ink-3">No active disputes.</div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {shownDisputes.map((d, i) => (
                      <DisputeBlock key={`${d.subject_entity}-${d.predicate}-${i}`} d={d} resolved={!isActiveDispute(d)} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {turn.sources.length > 0 && (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => setShowSources((s) => !s)}
                  aria-expanded={showSources}
                  className="flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-3 transition-colors hover:text-ink-1"
                >
                  <span className="inline-block transition-transform" style={{ transform: showSources ? "rotate(90deg)" : "none" }}>▸</span>
                  {turn.sources.length} source{turn.sources.length === 1 ? "" : "s"}
                </button>
                {showSources && (
                  <div className="mt-2 flex flex-col gap-2">
                    {turn.sources.map((s, i) => (
                      <SourceLine key={s.claim_id} s={s} n={i + 1} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {turn.sources.length === 0 && turn.disputes.length === 0 && (
              <div className="mt-2 font-mono text-[10px] text-ink-3">No cited sources</div>
            )}
          </>
        )}
      </GlassCard>
    </div>
  );
}

export default function TwinView() {
  const members = useProjectMembers(PROJECT_ID);
  const twin = useTwinQuery();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [focused, setFocused] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);

  // Default selection: Juan Garcia if present, else the first member.
  useEffect(() => {
    if (selectedId == null && members.data && members.data.length > 0) {
      const juan = members.data.find((m) => /juan\s+garcia/i.test(m.name));
      setSelectedId((juan ?? members.data[0]).user_id);
    }
  }, [members.data, selectedId]);

  const selected: ProjectMember | undefined = useMemo(
    () => members.data?.find((m) => m.user_id === selectedId),
    [members.data, selectedId],
  );

  // Switching the person you're talking to resets the conversation context.
  const onPickEmployee = (id: number) => {
    setSelectedId(id);
    setTurns([]);
  };

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const onSend = (e: React.FormEvent) => {
    e.preventDefault();
    const question = input.trim();
    if (!question || twin.isPending) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question, status: "pending", sources: [], disputes: [] }]);
    setInput("");
    twin.mutate(
      { question, project_id: PROJECT_ID },
      {
        onSuccess: (data) =>
          setTurns((t) => t.map((x) => (x.id === id ? { ...x, status: "done", answer: data.answer, sources: data.sources ?? [], disputes: data.disputes ?? [] } : x))),
        onError: (err) =>
          setTurns((t) => t.map((x) => (x.id === id ? { ...x, status: "error", error: err instanceof Error ? err.message : "Query failed" } : x))),
      },
    );
  };

  const name = selected?.name ?? "this employee";

  return (
    <div className="flex h-full flex-col">
      {/* Employee selector — context for the conversation (§7.6 process framing). */}
      <div className="flex items-center gap-3 border-b px-4 py-3" style={{ borderColor: "var(--card-hairline)" }}>
        <div className="min-w-0">
          <div className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-3">Knowledge captured from</div>
          <div className="mt-0.5 flex items-center gap-2">
            <SafeText text={selected?.name ?? "—"} className="truncate font-body text-[15px] font-semibold text-ink-1" />
            {selected?.role && <span className="rounded-full px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-2" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}><SafeText text={selected.role} /></span>}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">Twin</span>
          <select
            value={selectedId ?? ""}
            onChange={(e) => onPickEmployee(Number(e.target.value))}
            disabled={members.isPending || !members.data?.length}
            className="rounded-md px-2.5 py-1.5 font-mono text-[12px] text-ink-1 outline-none disabled:opacity-50"
            style={{ background: "var(--field-bg)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
          >
            {members.isPending && <option>Loading…</option>}
            {members.data?.map((m) => (
              <option key={m.user_id} value={m.user_id}>{m.name} — {m.role}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Conversation thread */}
        <div className="flex min-w-0 flex-1 flex-col border-r" style={{ borderColor: "var(--card-hairline)" }}>
          <div ref={threadRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
            {members.isError ? (
              <div className="grid h-full place-items-center px-8 text-center">
                <div className="flex items-center gap-2">
                  <Dot s="alert" glow />
                  <span className="font-mono text-[12px] text-ink-2">Couldn't load employees</span>
                </div>
              </div>
            ) : turns.length === 0 ? (
              <div className="grid h-full place-items-center px-8 text-center">
                <div className="max-w-md">
                  <div className="text-[14px] leading-relaxed text-ink-2">
                    Ask a question about <SafeText text={name} className="font-semibold text-ink-1" />'s knowledge
                  </div>
                  <div className="mt-2 font-mono text-[11.5px] text-ink-3">e.g. “Who manages the ETL pipeline?”</div>
                </div>
              </div>
            ) : (
              turns.map((t) => (
                <div key={t.id} className="space-y-3">
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-lg px-3 py-2 text-[13px] text-ink-1" style={{ background: "color-mix(in srgb, var(--accent) 14%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent)" }}>
                      <SafeText text={t.question} as="p" className="font-body leading-relaxed" />
                    </div>
                  </div>
                  <TwinBubble turn={t} />
                </div>
              ))
            )}
          </div>

          <form onSubmit={onSend} className="flex gap-2 border-t p-3" style={{ borderColor: "var(--card-hairline)" }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              placeholder={`Ask about ${name}'s knowledge…`}
              disabled={twin.isPending || !selected}
              className="min-w-0 flex-1 rounded-md px-3 py-2 font-body text-[13.5px] text-ink-1 outline-none placeholder:text-ink-3 disabled:opacity-50"
              style={{
                background: "var(--field-bg)",
                boxShadow: focused
                  ? "inset 0 0 0 1px var(--accent), 0 0 0 3px rgba(245,99,30,0.16)"
                  : "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)",
              }}
            />
            <Button type="submit" variant="primary" loading={twin.isPending} disabled={!input.trim() || !selected}>
              Ask
            </Button>
          </form>
        </div>

        {/* Coverage sidebar for the selected employee's project. */}
        <div className="hidden w-[280px] flex-none overflow-y-auto lg:block">
          <CoverageOverview projectId={PROJECT_ID} />
        </div>
      </div>
    </div>
  );
}
