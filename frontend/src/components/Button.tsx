import type { ButtonHTMLAttributes, ReactNode } from "react";

// Kit button (DESIGN.md §3). default = frosted glass + hairline · primary =
// terracotta gradient CTA (orange is signal only, so CTAs are terracotta) ·
// tint = orange-tinted glass · danger = muted red tint (never a bright fill).
export type ButtonVariant = "default" | "primary" | "tint" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  loading?: boolean;
  children: ReactNode;
}

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-btn px-3.5 py-2 font-body text-[13px] font-semibold transition-[filter,transform] duration-100 active:translate-y-px disabled:opacity-50 disabled:pointer-events-none";

const VARIANT: Record<ButtonVariant, { className: string; style?: React.CSSProperties }> = {
  default: {
    className: "text-ink-1 hover:brightness-[0.98]",
    style: { background: "var(--field-bg)", boxShadow: "inset 0 1px 0 var(--card-edge), inset 0 0 0 1px var(--card-hairline)" },
  },
  primary: {
    className: "bg-btn-primary text-white hover:brightness-105",
    style: {
      boxShadow:
        "inset 0 1px 0 rgba(255,255,255,0.30), inset 0 0 0 1px rgba(150,62,32,0.45), 0 5px 14px -5px rgba(180,82,48,0.45)",
    },
  },
  tint: {
    className: "text-ink-1 hover:brightness-[0.98]",
    style: {
      background: "color-mix(in srgb, var(--accent) 14%, transparent)",
      boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--accent) 38%, transparent)",
    },
  },
  danger: {
    className: "text-ink-1 hover:brightness-[0.98]",
    style: {
      background: "color-mix(in srgb, var(--red) 12%, transparent)",
      boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 34%, transparent)",
    },
  },
};

export function Button({ variant = "default", loading, disabled, children, className = "", ...rest }: ButtonProps) {
  const v = VARIANT[variant];
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`${BASE} ${v.className} ${className}`}
      style={v.style}
      {...rest}
    >
      {loading && (
        <span
          className={`h-3 w-3 animate-spin rounded-full border-2 ${
            variant === "primary" ? "border-white/90" : "border-ink-3"
          } border-t-transparent motion-reduce:animate-none`}
        />
      )}
      {children}
    </button>
  );
}
