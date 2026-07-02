import { useState } from "react";
import { SafeText } from "../../components/SafeText";
import { Loading } from "../../components/Loading";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { Dot } from "../../components/Dot";
import { useTwinQuery, type TwinResponse } from "../../hooks/useTwin";

interface Props {
  projectId: number;
  onResult: (result: TwinResponse) => void;
}

export default function TwinChat({ projectId, onResult }: Props) {
  const [question, setQuestion] = useState("");
  const [focused, setFocused] = useState(false);
  const mutation = useTwinQuery();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    mutation.mutate({ question: question.trim(), project_id: projectId }, { onSuccess: (data) => onResult(data) });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {mutation.data && (
          <GlassCard className="p-card-lg">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">Answer</div>
            {/* Twin answer text via SafeText. */}
            <SafeText text={mutation.data.answer} as="div" className="whitespace-pre-wrap font-body text-[13.5px] leading-relaxed text-ink-1" />
            {mutation.data.sources.length > 0 && (
              <div className="mt-3 font-mono text-[10px] text-ink-3">{mutation.data.sources.length} source(s) cited</div>
            )}
          </GlassCard>
        )}
        {mutation.isPending && <Loading message="Asking the twin…" />}
        {mutation.isError && (
          <div className="flex items-center gap-2">
            <Dot s="alert" glow />
            <SafeText text={mutation.error?.message || "query failed"} className="font-mono text-[12px] text-ink-2" />
          </div>
        )}
      </div>
      <form onSubmit={handleSubmit} className="flex gap-2 border-t p-4" style={{ borderColor: "var(--card-hairline)" }}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Ask the twin…"
          disabled={mutation.isPending}
          className="min-w-0 flex-1 rounded-md px-3 py-2 font-body text-[13.5px] text-ink-1 outline-none placeholder:text-ink-3"
          style={{
            background: "var(--field-bg)",
            boxShadow: focused
              ? "inset 0 0 0 1px var(--accent), 0 0 0 3px rgba(245,99,30,0.16)"
              : "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)",
          }}
        />
        <Button type="submit" variant="primary" loading={mutation.isPending} disabled={!question.trim()}>
          Ask
        </Button>
      </form>
    </div>
  );
}
