import { useRef, type CSSProperties, type PointerEvent, type ReactNode } from "react";

// Created once (matchMedia allocates) — `.matches` stays live, so we just read
// it on each pointermove instead of calling matchMedia 60×/s.
const reduceMotionQuery =
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}

// Floating frosted card — the Liquid Glass signature (DESIGN.md §2.5 / §3). The
// specular highlight follows the cursor: pointermove updates --mx/--my, which
// the `.glass-card::after` radial reads. That radial is hover-gated in CSS
// (opacity 0 at rest → fades in only while hovered). Honors prefers-reduced-motion
// (the specular just stays at its last position).
export function GlassCard({ children, className = "", style }: GlassCardProps) {
  const ref = useRef<HTMLDivElement>(null);

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    if (reduceMotionQuery?.matches) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${((e.clientX - r.left) / r.width) * 100}%`);
    el.style.setProperty("--my", `${((e.clientY - r.top) / r.height) * 100}%`);
  };

  return (
    <div
      ref={ref}
      onPointerMove={onPointerMove}
      className={`glass-card relative overflow-hidden rounded-lg bg-glass-card shadow-elev transition-[transform,box-shadow] duration-150 ease-out hover:-translate-y-0.5 hover:shadow-elev-hi motion-reduce:transition-none motion-reduce:hover:translate-y-0 ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}
