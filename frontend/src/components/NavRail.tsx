import type { ComponentType, ReactNode } from "react";
import { NavLink } from "react-router-dom";

// Per-section color legend (DESIGN.md §7.5). Each item carries its hue as the
// active left bar + LED dot + icon tint, so the rail reads as a who-does-what
// legend. `manager` (#D98C4A) is DEFERRED — not a route yet, intentionally absent.
type IconProps = { width?: number; height?: number };

function DashboardIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </svg>
  );
}
function SetupIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h5M8 12h8M8 16h6" strokeLinecap="round" />
    </svg>
  );
}
function InterviewIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <path d="M20 11.5a7.5 7.5 0 01-10.9 6.7L4 20l1.8-4.6A7.5 7.5 0 1120 11.5z" strokeLinejoin="round" />
    </svg>
  );
}
function TwinIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5.5 20a6.5 6.5 0 0113 0" strokeLinecap="round" />
    </svg>
  );
}
function GraphIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <circle cx="6" cy="6" r="2.4" />
      <circle cx="18" cy="8" r="2.4" />
      <circle cx="9" cy="18" r="2.4" />
      <path d="M8 7.2l8 0.6M7.4 8.1l1.4 8M11 17l6-7" strokeLinecap="round" />
    </svg>
  );
}
function ExplorerIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.5 15.5L21 21" strokeLinecap="round" />
    </svg>
  );
}
function IngestionIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <path d="M4 14v4a2 2 0 002 2h12a2 2 0 002-2v-4" strokeLinecap="round" />
      <path d="M12 3v11M8 10l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function OntologyIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <circle cx="12" cy="5" r="2.4" />
      <circle cx="5" cy="18" r="2.4" />
      <circle cx="19" cy="18" r="2.4" />
      <path d="M12 7.4v4.2M11 12.4l-4.6 3.4M13 12.4l4.6 3.4" strokeLinecap="round" />
    </svg>
  );
}
function DecisionsIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <rect x="4" y="3.5" width="16" height="17" rx="2" />
      <path d="M8 9l2 2 3.5-3.5M8 15h6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function SettingsIcon({ width = 17, height = 17 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} width={width} height={height}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" strokeLinecap="round" />
    </svg>
  );
}

type Section = { to: string; label: string; color: string; Icon: ComponentType<IconProps> };
const GROUPS: { label: string; items: Section[] }[] = [
  {
    label: "Workspace",
    items: [
      { to: "/dashboard", label: "Dashboard", color: "var(--sec-dashboard)", Icon: DashboardIcon },
      { to: "/explorer", label: "Explorer", color: "var(--sec-explorer)", Icon: ExplorerIcon },
      { to: "/setup", label: "Setup", color: "var(--sec-setup)", Icon: SetupIcon },
      { to: "/interview", label: "Interview", color: "var(--sec-interview)", Icon: InterviewIcon },
      { to: "/twin", label: "Twin", color: "var(--sec-twin)", Icon: TwinIcon },
    ],
  },
  {
    label: "Governance",
    items: [
      { to: "/graph", label: "Graph", color: "var(--sec-graph)", Icon: GraphIcon },
      { to: "/ontology", label: "Ontology", color: "var(--sec-ontology)", Icon: OntologyIcon },
      { to: "/ingestion", label: "Ingestion", color: "var(--sec-ingestion)", Icon: IngestionIcon },
      { to: "/decisions", label: "Decisions", color: "var(--sec-decisions)", Icon: DecisionsIcon },
    ],
  },
];

const ROW_BASE =
  "relative flex w-full items-center gap-[11px] rounded-[11px] px-[11px] py-[9px] text-left font-body text-[13px] transition-colors";

const activeStyle = {
  background: "var(--card-bg)",
  boxShadow: "inset 0 0 0 1px var(--card-hairline), 0 1px 2px rgba(0,0,0,0.12)",
};

function RowInner({ active, color, Icon, label }: { active: boolean; color: string; Icon: ComponentType<IconProps>; label: string }): ReactNode {
  return (
    <>
      {active && (
        <span
          className="absolute -left-2 top-1/2 h-[18px] w-[3px] -translate-y-1/2 rounded-[3px]"
          style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        />
      )}
      <span className="grid flex-none place-items-center" style={active ? { color } : undefined}>
        <Icon />
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {active && <span className="h-[6px] w-[6px] flex-none rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />}
    </>
  );
}

export function NavRail({ onOpenSettings, settingsOpen }: { onOpenSettings: () => void; settingsOpen: boolean }) {
  return (
    <nav
      aria-label="Sections"
      className="z-[2] flex min-h-0 flex-col gap-[6px] overflow-y-auto rounded-xl p-4"
      style={{
        background: "var(--tray-bg)",
        backdropFilter: "blur(22px) saturate(1.3)",
        WebkitBackdropFilter: "blur(22px) saturate(1.3)",
        boxShadow: "var(--tray-shadow)",
      }}
    >
      {GROUPS.map((group, gi) => (
        <div key={group.label} className={gi > 0 ? "mt-3" : undefined}>
          <div className="px-2.5 pb-1.5 pt-1 font-mono text-[9px] font-semibold uppercase tracking-[0.16em] text-ink-3">{group.label}</div>
          {group.items.map(({ to, label, color, Icon }) => (
            <NavLink
              key={to}
              to={to}
              data-testid={`nav-${label.toLowerCase()}`}
              className={({ isActive }) => `${ROW_BASE} ${isActive ? "font-semibold text-ink-1" : "text-ink-2 hover:text-ink-1"}`}
              style={({ isActive }) => (isActive ? activeStyle : undefined)}
            >
              {({ isActive }) => <RowInner active={isActive} color={color} Icon={Icon} label={label} />}
            </NavLink>
          ))}
        </div>
      ))}

      <div className="flex-1" />
      <div className="px-2.5 pb-1 pt-1 font-mono text-[9px] font-semibold uppercase tracking-[0.16em] text-ink-3">System</div>

      <button
        type="button"
        data-testid="nav-settings"
        onClick={onOpenSettings}
        aria-haspopup="dialog"
        aria-expanded={settingsOpen}
        className={`${ROW_BASE} ${settingsOpen ? "font-semibold text-ink-1" : "text-ink-2 hover:text-ink-1"}`}
        style={settingsOpen ? activeStyle : undefined}
      >
        <RowInner active={settingsOpen} color="var(--sec-settings)" Icon={SettingsIcon} label="Settings" />
      </button>
    </nav>
  );
}
