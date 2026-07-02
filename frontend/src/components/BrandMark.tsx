// Shared brand mark (DESIGN.md §5): square outline + 3 bars, the MIDDLE bar
// surgical orange, the others currentColor. Rendered BARE (no glass chip). Set
// the container's color (text-ink-1) so currentColor adapts across themes.
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <rect x="2" y="2" width="28" height="28" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
      <line x1="8" y1="10" x2="24" y2="10" stroke="currentColor" strokeWidth="2.4" />
      <line x1="8" y1="16" x2="20" y2="16" stroke="var(--accent)" strokeWidth="2.4" />
      <line x1="8" y1="22" x2="24" y2="22" stroke="currentColor" strokeWidth="2.4" />
    </svg>
  );
}

// Mark + KnowTwin wordmark, for the nav / auth header.
export function BrandLockup({ size = 22 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2.5 text-ink-1">
      <BrandMark size={size} />
      <span className="font-mono text-[19px] text-ink-1">
        Know<b className="font-medium">Twin</b>
      </span>
    </div>
  );
}
