import { useState } from "react";

const cmdKBadge =
  typeof navigator !== "undefined" && /mac/i.test(navigator.platform) ? "⌘K" : "Ctrl K";

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={17} height={17}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}
function XIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} width={14} height={14}>
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  );
}

interface SearchFieldProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  resultCount?: number;
  loading?: boolean;
  clearLabel?: string;
}

// Search field (DESIGN.md §3): generous height, orange focus ring, result count
// + clear when typing.
export function SearchField({ value, onChange, placeholder, resultCount, loading, clearLabel = "Clear" }: SearchFieldProps) {
  const [focused, setFocused] = useState(false);
  return (
    <div
      className="flex h-12 min-w-0 flex-1 items-center gap-3 rounded-md px-4"
      style={{
        background: "var(--field-bg)",
        boxShadow: focused
          ? "inset 0 0 0 1px var(--accent), 0 0 0 3px rgba(245,99,30,0.16)"
          : "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)",
      }}
    >
      <span className="flex-none text-ink-3">
        <SearchIcon />
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={placeholder}
        className="min-w-0 flex-1 border-none bg-transparent font-body text-[13.5px] text-ink-1 outline-none placeholder:text-ink-3"
      />
      {loading && <span className="h-3.5 w-3.5 flex-none animate-spin rounded-full border-2 border-ink-3 border-t-transparent motion-reduce:animate-none" />}
      {value && resultCount != null && !loading && (
        <span
          className="flex-none rounded-[20px] px-[7px] py-0.5 font-mono text-[10px] font-semibold text-ink-1"
          style={{ background: "color-mix(in srgb, var(--accent) 18%, transparent)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent)" }}
        >
          {resultCount}
        </span>
      )}
      {value ? (
        <button type="button" onClick={() => onChange("")} aria-label={clearLabel} className="flex-none text-ink-3 transition-colors hover:text-ink-1">
          <XIcon />
        </button>
      ) : (
        <span
          className="flex-none rounded-md px-[7px] py-[3px] font-mono text-[10.5px] text-ink-3"
          style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}
        >
          {cmdKBadge}
        </span>
      )}
    </div>
  );
}
