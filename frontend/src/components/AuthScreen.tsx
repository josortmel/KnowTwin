import { useState, type FormEvent } from "react";
import { setApiKey } from "../lib/auth";
import { GlassCard } from "./GlassCard";
import { BrandLockup } from "./BrandMark";
import { Button } from "./Button";
import { Dot } from "./Dot";

// First-run auth (DESIGN.md §8 point 10 / §3): glass card on the backdrop,
// accent focus ring on the field, terracotta primary CTA. The key is sent to
// main via the bridge and stored encrypted; it never lives in the renderer.
export function AuthScreen({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [key, setKey] = useState("");
  const [show, setShow] = useState(false);
  const [focused, setFocused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canSubmit = key.trim().length > 0 && !busy;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const ok = await setApiKey(key.trim());
      if (ok) onAuthenticated();
      else setError("Could not store the key — encryption may be unavailable on this device.");
    } catch {
      setError("Could not store the key — encryption may be unavailable on this device.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-screen w-full place-items-center p-8">
      <div className="flex w-full max-w-[380px] flex-col items-center">
        <div className="mb-6">
          <BrandLockup size={22} />
        </div>

        <GlassCard className="w-full p-6">
          <form onSubmit={onSubmit}>
            <h1 className="text-[18px] font-semibold text-ink-1">Connect to KnowTwin</h1>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
              Enter your API key. It's stored encrypted on this device and never leaves it.
            </p>

            <div
              className="mt-5 flex items-center gap-2 rounded-md px-3"
              style={{
                height: "46px",
                background: "var(--field-bg)",
                boxShadow: focused
                  ? "inset 0 0 0 1px var(--accent), 0 0 0 3px rgba(245,99,30,0.16)"
                  : "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)",
              }}
            >
              <input
                type={show ? "text" : "password"}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                placeholder="knowtwin_…"
                aria-label="API key"
                autoFocus
                autoComplete="off"
                spellCheck={false}
                className="min-w-0 flex-1 border-none bg-transparent font-mono text-[13px] text-ink-1 outline-none placeholder:text-ink-3"
              />
              <button
                type="button"
                onClick={() => setShow((s) => !s)}
                aria-label={show ? "Hide key" : "Show key"}
                className="flex-none font-mono text-[10.5px] text-ink-3 transition-colors hover:text-ink-1"
              >
                {show ? "Hide" : "Show"}
              </button>
            </div>

            {error && (
              <div
                role="alert"
                className="mt-3 flex items-start gap-2 rounded-md px-3 py-2.5"
                style={{ background: "rgba(222,70,48,0.08)", boxShadow: "inset 0 0 0 1px rgba(222,70,48,0.25)" }}
              >
                <Dot s="alert" glow className="mt-[3px]" />
                <span className="text-[12px] leading-relaxed text-ink-1">{error}</span>
              </div>
            )}

            <Button type="submit" variant="primary" loading={busy} disabled={!canSubmit} className="mt-5 w-full py-3">
              {busy ? "Connecting…" : "Connect"}
            </Button>
          </form>
        </GlassCard>
      </div>
    </main>
  );
}
