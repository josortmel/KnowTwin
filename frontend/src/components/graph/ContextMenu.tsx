import { SafeText } from "../SafeText";
import type { GNode } from "./graphTypes";

function MenuItem({ label, onClick, disabled, danger }: { label: React.ReactNode; onClick: () => void; disabled?: boolean; danger?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full items-center whitespace-nowrap px-3 py-1.5 text-left font-mono text-[11px] transition-colors hover:bg-[var(--inset)] disabled:cursor-not-allowed disabled:opacity-40"
      style={{ color: danger ? "var(--red)" : "var(--ink-1)" }}
    >
      {label}
    </button>
  );
}

export interface GraphContextMenuProps {
  menu: { x: number; y: number; node: GNode | null };
  size: { w: number; h: number };
  isAdmin: boolean;
  mergeTarget: GNode | null;
  expanding: boolean;
  hasSelection: boolean;
  onClose: () => void;
  onInspect: (node: GNode) => void;
  onRecenter: (node: GNode) => void;
  onExpand: (node: GNode) => void;
  onMerge: (node: GNode, target: GNode) => void;
  onSelectVisible: () => void;
  onClearSelection: () => void;
}

export function GraphContextMenu(props: GraphContextMenuProps) {
  const { menu, size, isAdmin, mergeTarget, expanding, hasSelection, onClose } = props;
  return (
    <>
      <div className="absolute inset-0 z-20" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        className="absolute z-30 min-w-[150px] overflow-hidden rounded-md py-1"
        style={{ left: Math.min(menu.x, size.w - 170), top: Math.min(menu.y, size.h - 180), background: "var(--card-bg)", backdropFilter: "blur(22px) saturate(1.3)", WebkitBackdropFilter: "blur(22px) saturate(1.3)", boxShadow: "inset 0 0 0 1px var(--card-edge), 0 12px 30px -12px rgba(0,0,0,0.6)" }}
      >
        {menu.node ? (
          <>
            <MenuItem label="Inspect" onClick={() => props.onInspect(menu.node!)} />
            <MenuItem label="Re-center" onClick={() => props.onRecenter(menu.node!)} />
            <MenuItem label="Expand neighbors" disabled={expanding} onClick={() => props.onExpand(menu.node!)} />
            {/* merge is an admin action (POST /admin/merge-entities) → only admins see it */}
            {isAdmin && (
              <MenuItem
                label={mergeTarget ? <span>Merge into <SafeText text={mergeTarget.name} /></span> : "Merge (select 1 target)"}
                disabled={!mergeTarget}
                onClick={() => mergeTarget && props.onMerge(menu.node!, mergeTarget)}
              />
            )}
          </>
        ) : (
          <>
            <MenuItem label="Select all visible" onClick={props.onSelectVisible} />
            <MenuItem label="Clear selection" disabled={!hasSelection} onClick={props.onClearSelection} />
          </>
        )}
      </div>
    </>
  );
}
