import { SafeText } from "../components/SafeText";

export function InterviewPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">
        <SafeText text="Interview" />
      </h1>
      <p className="text-gray-600">
        <SafeText text="Conduct knowledge capture interview sessions. (P1.20)" />
      </p>
    </div>
  );
}
