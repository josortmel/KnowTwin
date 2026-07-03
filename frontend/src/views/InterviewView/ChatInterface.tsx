import { useState } from "react";
import { SafeText } from "../../components/SafeText";
import { Button } from "../../components/Button";
import { VoiceRecorder } from "./VoiceRecorder";

interface Message {
  role: "user" | "system";
  text: string;
  turn?: number;
  claimsCreated?: number;
  turnValue?: number;
}

interface ChatInterfaceProps {
  sessionId: string;
  onSendText: (text: string) => Promise<void>;
  onSendVoice: (file: File) => Promise<void>;
  messages: Message[];
  disabled?: boolean;
}

export function ChatInterface({ sessionId: _sid, onSendText, onSendVoice, messages, disabled }: ChatInterfaceProps) {
  void _sid;
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;
    setSending(true);
    try {
      await onSendText(input.trim());
      setInput("");
    } finally {
      setSending(false);
    }
  };

  const handleVoice = async (file: File) => {
    setSending(true);
    try {
      await onSendVoice(file);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto space-y-3 p-4">
        {messages.length === 0 && !sending && (
          <div className="grid h-full place-items-center px-6 text-center font-mono text-[12px] text-ink-3">
            This session has no recorded content
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className="max-w-[80%] rounded-lg px-3 py-2 text-[13px] text-ink-1"
              style={
                m.role === "user"
                  ? { background: "color-mix(in srgb, var(--accent) 14%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent)" }
                  : { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }
              }
            >
              <SafeText text={m.text} as="p" className="font-body leading-relaxed" />
              {m.role === "system" && m.claimsCreated != null && (
                <div className="mt-1 font-mono text-[10px] tabular-nums text-ink-3">
                  {m.claimsCreated} claims · value {m.turnValue?.toFixed(2)}
                </div>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="animate-pulse rounded-lg px-3 py-2 font-mono text-[12px] text-ink-3 motion-reduce:animate-none" style={{ background: "var(--inset)" }}>
              Processing…
            </div>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 border-t p-3" style={{ borderColor: "var(--card-hairline)" }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={disabled || sending}
          placeholder="Type your response…"
          className="min-w-0 flex-1 rounded-md px-3 py-2 font-body text-[13.5px] text-ink-1 outline-none placeholder:text-ink-3 disabled:opacity-50"
          style={{ background: "var(--field-bg)", boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)" }}
        />
        <VoiceRecorder onRecorded={handleVoice} disabled={disabled || sending} />
        <Button type="submit" variant="primary" disabled={disabled || sending || !input.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}

export type { Message };
