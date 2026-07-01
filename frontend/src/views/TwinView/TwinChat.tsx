import { useState } from 'react';
import { SafeText } from '../../components/SafeText';
import { Loading } from '../../components/Loading';
import { useTwinQuery, type TwinResponse } from '../../hooks/useTwin';

interface Props {
  projectId: number;
  onResult: (result: TwinResponse) => void;
}

export default function TwinChat({ projectId, onResult }: Props) {
  const [question, setQuestion] = useState('');
  const mutation = useTwinQuery();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    mutation.mutate(
      { question: question.trim(), project_id: projectId },
      { onSuccess: (data) => onResult(data) },
    );
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {mutation.data && (
          <div className="bg-gray-50 rounded p-4">
            <h3 className="font-semibold text-sm text-gray-500 mb-2">Answer</h3>
            <div className="whitespace-pre-wrap">
              <SafeText text={mutation.data.answer} />
            </div>
            {mutation.data.sources.length > 0 && (
              <div className="mt-3 text-xs text-gray-400">
                <SafeText text={`${mutation.data.sources.length} source(s) cited`} />
              </div>
            )}
          </div>
        )}
        {mutation.isPending && <Loading />}
        {mutation.isError && (
          <div className="text-red-600 text-sm">
            <SafeText text={`Error: ${mutation.error?.message || 'query failed'}`} />
          </div>
        )}
      </div>
      <form onSubmit={handleSubmit} className="border-t p-4 flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask the twin..."
          className="flex-1 border rounded px-3 py-2 text-sm"
          disabled={mutation.isPending}
        />
        <button
          type="submit"
          disabled={mutation.isPending || !question.trim()}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
        >
          Ask
        </button>
      </form>
    </div>
  );
}
