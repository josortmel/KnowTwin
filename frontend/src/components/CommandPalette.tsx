import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { SafeText } from "./SafeText";
import { useGraphSearch } from "../hooks/useGraph";

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={17} height={17}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}

function Hk({ keys, label }: { keys: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <kbd className="rounded px-[5px] py-[2px] text-[10px] text-ink-2" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
        {keys}
      </kbd>
      <span>{label}</span>
    </span>
  );
}

// ⌘K entity jump. Fuzzy /graph/search → select navigates to the graph centered on
// the entity. Self-contained: AppShell owns the open flag + the ⌘K listener.
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(id);
  }, [q]);

  // Reset on open/close.
  useEffect(() => {
    if (open) {
      setQ("");
      setDebounced("");
      setSel(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const search = useGraphSearch(debounced);
  const results = useMemo(() => (search.data ?? []).slice(0, 8), [search.data]);
  const searching = debounced.trim().length > 0;
  const loading = searching && search.isFetching;

  useEffect(() => setSel(0), [results]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const activate = (name: string) => {
    navigate(`/graph?center=${encodeURIComponent(name)}`);
    onClose();
  };

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => (results.length ? (s + 1) % results.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => (results.length ? (s - 1 + results.length) % results.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const r = results[sel];
      if (r) activate(r.name);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center">
      <div onClick={onClose} aria-hidden className="absolute inset-0" style={{ background: "rgba(18,14,10,0.42)", backdropFilter: "blur(4px)", WebkitBackdropFilter: "blur(4px)" }} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative mt-[16vh] flex max-h-[64vh] w-[640px] max-w-[92vw] flex-col overflow-hidden rounded-xl"
        style={{ background: "var(--card-bg)", backdropFilter: "blur(22px) saturate(1.3)", WebkitBackdropFilter: "blur(22px) saturate(1.3)", boxShadow: "inset 0 0 0 1px var(--card-edge), 0 30px 80px -24px rgba(0,0,0,0.6)" }}
      >
        <div className="flex items-center gap-3 border-b border-[var(--card-hairline)] px-4 py-3.5">
          <span className="flex-none text-ink-3">
            <SearchIcon />
          </span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search entities — jump to the graph…"
            aria-label="Search entities"
            role="combobox"
            aria-expanded
            aria-controls="cmdk-listbox"
            aria-activedescendant={results[sel] ? `cmdk-opt-${sel}` : undefined}
            aria-autocomplete="list"
            className="min-w-0 flex-1 bg-transparent font-body text-[15px] text-ink-1 outline-none placeholder:text-ink-3"
          />
          <kbd className="flex-none rounded-md px-[7px] py-[3px] font-mono text-[10px] text-ink-3" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
            esc
          </kbd>
        </div>

        <div ref={listRef} id="cmdk-listbox" role="listbox" className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {!searching ? (
            <div className="grid place-items-center py-10 font-mono text-[12px] text-ink-3">Type to search entities in the graph.</div>
          ) : loading ? (
            <div className="flex flex-col gap-2.5 p-3">
              {[0, 1, 2, 3].map((i) => (
                <span key={i} className="h-[14px] animate-pulse rounded-sm" style={{ background: "var(--inset)", width: `${90 - i * 9}%` }} />
              ))}
            </div>
          ) : results.length === 0 ? (
            <div className="grid place-items-center py-10 font-mono text-[12px] text-ink-3">No matching entities.</div>
          ) : (
            results.map((r, i) => (
              <button
                key={r.id}
                type="button"
                id={`cmdk-opt-${i}`}
                data-idx={i}
                role="option"
                aria-selected={i === sel}
                onMouseEnter={() => setSel(i)}
                onClick={() => activate(r.name)}
                className="grid w-full grid-cols-[18px_1fr_auto] items-center gap-3 rounded-md px-3 py-2.5 text-left"
                style={i === sel ? { background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" } : undefined}
              >
                <span className="grid h-[18px] place-items-center">
                  <span className="h-[8px] w-[8px] rounded-full" style={{ background: "var(--sec-graph)", boxShadow: "0 0 7px var(--sec-graph)" }} />
                </span>
                <span className="min-w-0 truncate text-[13px] text-ink-1">
                  <SafeText text={r.name} />
                </span>
                {r.similarity != null && <span className="flex-none font-mono text-[9.5px] tabular-nums text-ink-3">{r.similarity.toFixed(2)}</span>}
              </button>
            ))
          )}
        </div>

        <div className="flex items-center gap-4 border-t border-[var(--card-hairline)] px-4 py-2.5 font-mono text-[10px] text-ink-3">
          <Hk keys="↑↓" label="navigate" />
          <Hk keys="↵" label="open" />
          <Hk keys="esc" label="close" />
          {searching && results.length > 0 && <span className="ml-auto">{results.length} results</span>}
        </div>
      </div>
    </div>
  );
}
