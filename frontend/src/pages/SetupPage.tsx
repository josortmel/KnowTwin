import { SafeText } from "../components/SafeText";

export function SetupPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">
        <SafeText text="Setup & Curation" />
      </h1>
      <p className="text-gray-600">
        <SafeText text="Upload documents, configure entities, run curator. (P1.19)" />
      </p>
    </div>
  );
}
