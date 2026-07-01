import { SafeText } from "../components/SafeText";

export function TwinPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">
        <SafeText text="Twin Query" />
      </h1>
      <p className="text-gray-600">
        <SafeText text="Ask the digital twin questions about captured knowledge. (P1.21)" />
      </p>
    </div>
  );
}
