import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../lib/api";
import { connectWs, type WsEvent } from "../../lib/ws";
import { useCreateSession, useStartSession, useRespond, useUploadVoice, useCloseSession, useSuggestedTopics } from "../../hooks/useInterviews";
import { useMe, useScore } from "../../hooks/useScore";
import { ScoreChip } from "../../components/ScoreChip";
import { CoverageStateBadge } from "../../components/CoverageStateBadge";
import { SafeText } from "../../components/SafeText";
import { Button } from "../../components/Button";
import { ChatInterface, type Message } from "./ChatInterface";
import { TopicIndicator } from "./TopicIndicator";
import { CoverageBar } from "./CoverageBar";
import { ClaimSidebar } from "./ClaimSidebar";
import { SessionHistory } from "./SessionHistory";

const PROJECT_ID = 1;

interface CoverageData {
  overall_coverage_pct: number;
  entity_count: number;
}

export function InterviewView() {
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [topic, setTopic] = useState<string | null>(null);
  const [converged, setConverged] = useState(false);
  const [claimIds, setClaimIds] = useState<string[]>([]);
  const [wsCoverage, setWsCoverage] = useState<number | null>(null);
  const wsRef = useRef<ReturnType<typeof connectWs> | null>(null);

  const createSession = useCreateSession(PROJECT_ID);
  const startSession = useStartSession();
  const closeSession = useCloseSession();
  const suggestedTopics = useSuggestedTopics(PROJECT_ID);
  const [newTopic, setNewTopic] = useState("");

  // A Process next-step can deep-link here with a gap to interview about.
  const [searchParams] = useSearchParams();
  const topicParam = searchParams.get("topic");
  useEffect(() => {
    if (topicParam) setNewTopic(topicParam);
  }, [topicParam]);

  const { data: coverage } = useQuery<CoverageData>({
    queryKey: ["coverage", PROJECT_ID],
    queryFn: () => get(`/twin/coverage?project_id=${PROJECT_ID}`),
  });

  // Employee's own knowledge-capture score (§7.6). Absent for non-employees.
  const me = useMe();
  const score = useScore(PROJECT_ID, me.data?.user_id);

  useEffect(() => {
    if (!activeSession) return;
    const ws = connectWs(PROJECT_ID, activeSession, (event: WsEvent) => {
      if (event.type === "coverage_update" && typeof event.data.coverage_pct === "number") {
        setWsCoverage(event.data.coverage_pct as number);
      }
      if (event.type === "topic_change") {
        setConverged(true);
      }
      if (event.type === "new_claim" && typeof event.data.claim_id === "string") {
        setClaimIds((prev) => [...prev, event.data.claim_id as string]);
      }
    });
    wsRef.current = ws;
    return () => { ws.close(); wsRef.current = null; };
  }, [activeSession]);

  const handleCreate = async () => {
    const topicName = newTopic.trim() || "General interview";
    const s = await createSession.mutateAsync(topicName);
    setActiveSession(s.id);
    const result = await startSession.mutateAsync(s.id);
    setTopic(result.topic);
    setMessages([{ role: "system", text: `Interview started. Let's talk about: ${result.topic}` }]);
    setClaimIds([]);
    setConverged(false);
    setWsCoverage(null);
    setNewTopic("");
  };

  const handleSelect = (id: string) => {
    setActiveSession(id);
    setMessages([]);
    setClaimIds([]);
    setConverged(false);
    setWsCoverage(null);
  };

  // Return to the session list without ending the session (End session closes it).
  const handleBack = () => {
    setActiveSession(null);
    setMessages([]);
    setTopic(null);
    setClaimIds([]);
    setConverged(false);
    setWsCoverage(null);
  };

  const respond = useRespond(activeSession || "");
  const uploadVoice = useUploadVoice(activeSession || "");

  const handleSendText = useCallback(async (text: string) => {
    setMessages((prev) => [...prev, { role: "user", text }]);
    try {
      const result = await respond.mutateAsync(text);
      // The interviewer's LLM-generated follow-up question is the natural next
      // message; fall back to a status line if the backend returned none.
      const followUp = result.message?.trim();
      setMessages((prev) => [...prev, {
        role: "system",
        text: followUp
          || (result.converged
            ? `Topic covered. ${result.claims_created.length} new claims.`
            : `Extracted ${result.claims_created.length} claims (value: ${result.turn_value.toFixed(2)})`),
        turn: result.turn,
        claimsCreated: result.claims_created.length,
        turnValue: result.turn_value,
      }]);
      if (result.topic) setTopic(result.topic);
      setConverged(result.converged);
      setClaimIds((prev) => [...prev, ...result.claims_created]);
      if (result.coverage_pct != null) setWsCoverage(result.coverage_pct);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "system", text: `Error: ${e}` }]);
    }
  }, [respond]);

  const handleSendVoice = useCallback(async (file: File) => {
    setMessages((prev) => [...prev, { role: "user", text: "[voice note]" }]);
    try {
      const result = await uploadVoice.mutateAsync(file);
      const followUp = result.message?.trim();
      setMessages((prev) => [...prev, {
        role: "system",
        text: followUp || `Transcribed + extracted ${result.claims_created.length} claims`,
        turn: result.turn,
        claimsCreated: result.claims_created.length,
        turnValue: result.turn_value,
      }]);
      setClaimIds((prev) => [...prev, ...result.claims_created]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "system", text: `Voice error: ${e}` }]);
    }
  }, [uploadVoice]);

  const handleClose = async () => {
    if (activeSession) {
      await closeSession.mutateAsync(activeSession);
      setActiveSession(null);
      setMessages([]);
      setTopic(null);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-4 border-b px-4 py-3" style={{ borderColor: "var(--card-hairline)" }}>
        <div className="min-w-0 flex-1">
          <CoverageBar
            initialPct={coverage?.overall_coverage_pct ?? 0}
            entityCount={coverage?.entity_count ?? 0}
            wsPct={wsCoverage}
          />
        </div>
        {score.data && (
          <ScoreChip score={score.data.score} components={score.data.components} claimCount={score.data.claim_count} />
        )}
      </div>

      {!activeSession ? (
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="rounded-lg p-4" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
            <div className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">Start an interview</div>

            {/* Suggested topics from coverage gaps (§7.6 — where knowledge is thin). */}
            <div className="mt-3">
              <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Suggested topics</div>
              {suggestedTopics.isPending ? (
                <div className="flex flex-wrap gap-2">
                  {[0, 1, 2, 3].map((i) => (
                    <span key={i} className="h-[26px] w-28 animate-pulse rounded-full motion-reduce:animate-none" style={{ background: "var(--card-bg)" }} />
                  ))}
                </div>
              ) : suggestedTopics.isError ? (
                <div className="font-mono text-[11px] text-ink-3">Couldn't load suggestions</div>
              ) : (suggestedTopics.data?.length ?? 0) === 0 ? (
                <div className="font-mono text-[11.5px] text-ink-3">Coverage looks solid — no gaps to suggest. Pick your own topic below.</div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {suggestedTopics.data!.map((t) => (
                    <button
                      key={t.entity_name}
                      type="button"
                      onClick={() => setNewTopic(t.entity_name)}
                      className="flex items-center gap-2 rounded-full px-2.5 py-1.5 text-left transition-colors hover:brightness-105"
                      style={{ background: newTopic === t.entity_name ? "color-mix(in srgb, var(--accent) 14%, transparent)" : "var(--card-bg)", boxShadow: newTopic === t.entity_name ? "inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent)" : "inset 0 0 0 1px var(--card-hairline)" }}
                      title={`criticality ${t.criticality.toFixed(1)} · ${t.coverage_pct}% covered`}
                    >
                      <CoverageStateBadge state={t.coverage_state} />
                      <SafeText text={t.entity_name} className="font-mono text-[11.5px] text-ink-1" />
                      <span className="font-mono text-[9.5px] tabular-nums text-ink-3">c{t.criticality.toFixed(0)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-4 flex gap-2">
              <input
                value={newTopic}
                onChange={(e) => setNewTopic(e.target.value)}
                placeholder="Or type a custom topic…"
                className="min-w-0 flex-1 rounded-md px-3 py-2 font-body text-[13.5px] text-ink-1 outline-none placeholder:text-ink-3"
                style={{ background: "var(--field-bg)", boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)" }}
              />
              <Button variant="primary" onClick={handleCreate} loading={createSession.isPending || startSession.isPending}>
                New Interview
              </Button>
            </div>
          </div>

          <SessionHistory projectId={PROJECT_ID} onSelect={handleSelect} />
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          <div className="flex flex-1 flex-col">
            <div className="flex items-center justify-between border-b px-4 py-2" style={{ borderColor: "var(--card-hairline)" }}>
              <div className="flex min-w-0 items-center gap-3">
                <button onClick={handleBack} className="flex flex-none items-center gap-1 rounded-md px-2 py-1 font-mono text-[11px] text-ink-2 transition-colors hover:text-ink-1" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                  <span aria-hidden>←</span> Back to sessions
                </button>
                <TopicIndicator topic={topic} converged={converged} />
              </div>
              <button onClick={handleClose} className="flex-none font-mono text-[11px] text-ink-3 transition-colors hover:text-ink-1">
                End session
              </button>
            </div>
            <div className="flex-1">
              <ChatInterface
                sessionId={activeSession}
                onSendText={handleSendText}
                onSendVoice={handleSendVoice}
                messages={messages}
              />
            </div>
          </div>
          <div className="w-72 overflow-y-auto border-l p-3" style={{ borderColor: "var(--card-hairline)", background: "var(--inset)" }}>
            <ClaimSidebar sessionId={activeSession} claimIds={claimIds} />
          </div>
        </div>
      )}
    </div>
  );
}
