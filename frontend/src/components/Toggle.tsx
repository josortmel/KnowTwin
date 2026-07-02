interface ToggleProps {
  on: boolean;
  onChange: (on: boolean) => void;
  label: string;
  disabled?: boolean;
}

// Kit toggle (DESIGN.md §3): orange gradient track when ON (orange = the "on"
// signal, §1.3), recessed well when OFF.
export function Toggle({ on, onChange, label, disabled }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="relative h-[21px] w-[38px] flex-none rounded-[30px] transition-[background] disabled:opacity-40"
      style={
        on
          ? { background: "linear-gradient(180deg, var(--toggle-on-start), var(--toggle-on-end))" }
          : { background: "var(--inset)", boxShadow: "inset 0 1px 2px var(--inset), inset 0 0 0 1px var(--card-hairline)" }
      }
    >
      <span
        className="absolute top-[2px] h-[17px] w-[17px] rounded-full transition-[left]"
        style={
          on
            ? { left: "calc(100% - 19px)", background: "#fff", boxShadow: "0 1px 2px rgba(120,50,10,0.4)" }
            : { left: "2px", background: "var(--card-bg)", boxShadow: "0 1px 2px rgba(0,0,0,0.3)" }
        }
      />
    </button>
  );
}
