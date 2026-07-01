import { useRef, useState } from "react";

const ALLOWED_MIME = ["audio/webm", "audio/mp4", "audio/wav", "audio/ogg"];
const MAX_SIZE_BYTES = 60 * 1024 * 1024;

interface VoiceRecorderProps {
  onRecorded: (file: File) => void;
  disabled?: boolean;
}

export function VoiceRecorder({ onRecorded, disabled }: VoiceRecorderProps) {
  const [recording, setRecording] = useState(false);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = ALLOWED_MIME.find((m) => MediaRecorder.isTypeSupported(m)) || "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      chunks.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.current.push(e.data);
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks.current, { type: recorder.mimeType });
        if (blob.size > MAX_SIZE_BYTES) {
          alert(`Recording too large (${(blob.size / 1024 / 1024).toFixed(1)}MB, max 60MB)`);
          return;
        }
        const ext = recorder.mimeType.includes("webm") ? ".webm" :
                     recorder.mimeType.includes("mp4") ? ".m4a" : ".wav";
        const file = new File([blob], `voice${ext}`, { type: recorder.mimeType });
        onRecorded(file);
      };

      mediaRecorder.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      alert("Microphone access denied");
    }
  };

  const stop = () => {
    mediaRecorder.current?.stop();
    setRecording(false);
  };

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={recording ? stop : start}
      className={`px-3 py-2 rounded text-sm font-medium ${
        recording
          ? "bg-red-500 text-white animate-pulse"
          : "bg-gray-200 text-gray-700 hover:bg-gray-300"
      } disabled:opacity-50`}
    >
      {recording ? "Stop" : "Voice"}
    </button>
  );
}
