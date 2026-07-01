import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../../lib/api";
import { connectWs, type WsEvent } from "../../lib/ws";
import { useCreateSession, useStartSession, useRespond, useUploadVoice, useCloseSession } from "../../hooks/useInterviews";
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
  const wsRef = useRef<WebSocket | null>(null);

  const createSession = useCreateSession(PROJECT_ID);
  const startSession = useStartSession();
  const closeSession = useCloseSession();

  const { data: coverage } = useQuery<CoverageData>({
    queryKey: ["coverage", PROJECT_ID],
    queryFn: () => get(`/twin/coverage?project_id=${PROJECT_ID}`),
  });

  useEffect(() => {
    if (!activeSession) return;
    const ws = connectWs(activeSession, (event: WsEvent) => {
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
    const s = await createSession.mutateAsync("General interview");
    setActiveSession(s.id);
    const result = await startSession.mutateAsync(s.id);
    setTopic(result.topic);
    setMessages([{ role: "system", text: `Interview started. Let's talk about: ${result.topic}` }]);
    setClaimIds([]);
    setConverged(false);
    setWsCoverage(null);
  };

  const handleSelect = (id: string) => {
    setActiveSession(id);
    setMessages([]);
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
      setMessages((prev) => [...prev, {
        role: "system",
        text: result.converged
          ? `Topic covered. ${result.claims_created.length} new claims.`
          : `Extracted ${result.claims_created.length} claims (value: ${result.turn_value.toFixed(2)})`,
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
      setMessages((prev) => [...prev, {
        role: "system",
        text: `Transcribed + extracted ${result.claims_created.length} claims`,
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
      <div className="px-4 py-3 border-b">
        <CoverageBar
          initialPct={coverage?.overall_coverage_pct ?? 0}
          entityCount={coverage?.entity_count ?? 0}
          wsPct={wsCoverage}
        />
      </div>

      {!activeSession ? (
        <div className="flex-1 p-4 space-y-4">
          <button
            onClick={handleCreate}
            disabled={createSession.isPending}
            className="px-4 py-2 bg-blue-500 text-white rounded text-sm font-medium hover:bg-blue-600 disabled:opacity-50"
          >
            New Interview
          </button>
          <SessionHistory projectId={PROJECT_ID} onSelect={handleSelect} />
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          <div className="flex-1 flex flex-col">
            <div className="px-4 py-2 border-b flex items-center justify-between">
              <TopicIndicator topic={topic} converged={converged} />
              <button
                onClick={handleClose}
                className="text-sm text-gray-500 hover:text-red-500"
              >
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
          <div className="w-72 border-l p-3 overflow-y-auto bg-gray-50">
            <ClaimSidebar sessionId={activeSession} claimIds={claimIds} />
          </div>
        </div>
      )}
    </div>
  );
}
