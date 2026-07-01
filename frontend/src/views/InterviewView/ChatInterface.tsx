import { useState } from "react";
import { SafeText } from "../../components/SafeText";
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
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
              m.role === "user"
                ? "bg-blue-500 text-white"
                : "bg-gray-100 text-gray-800"
            }`}>
              <SafeText text={m.text} as="p" />
              {m.role === "system" && m.claimsCreated != null && (
                <div className="text-xs mt-1 opacity-70">
                  {m.claimsCreated} claims · value {m.turnValue?.toFixed(2)}
                </div>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-400 animate-pulse">
              Processing...
            </div>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="border-t p-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={disabled || sending}
          placeholder="Type your response..."
          className="flex-1 px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50"
        />
        <VoiceRecorder onRecorded={handleVoice} disabled={disabled || sending} />
        <button
          type="submit"
          disabled={disabled || sending || !input.trim()}
          className="px-4 py-2 bg-blue-500 text-white rounded text-sm font-medium hover:bg-blue-600 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}

export type { Message };
