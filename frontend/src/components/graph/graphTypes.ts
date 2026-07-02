// Shared types + pure helpers for the Graph Studio pieces. Ported from EcoDB's
// graphTypes, adapted to KnowTwin: nodes are colored by COVERAGE STATE (§7.2), not
// entity type — the useful signal for offboarding is capture progress. The concrete
// color is resolved from CSS vars in the view (a canvas can't read vars) and stashed
// on `node.color`; these helpers stay palette-agnostic.

export type NodeId = number | string;
export type GNode = {
  id: NodeId;
  name: string;
  type?: string | null;
  degree: number;
  coverage_state?: string;
  color?: string; // resolved coverage color (set by the view)
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
  hot?: boolean;
};
export type GLink = { source: NodeId | GNode; target: NodeId | GNode; predicate: string };

// react-force-graph's imperative handle (only the methods we use).
export type FgHandle = {
  zoomToFit: (ms?: number, pad?: number) => void;
  d3ReheatSimulation: () => void;
  graph2ScreenCoords: (x: number, y: number) => { x: number; y: number };
  d3Force: (name: string) => { strength?: (v: number) => unknown; distance?: (v: number) => unknown } | undefined;
};

// Coverage states (§7.2). Order is the legend order (gap → complete).
export const COV_STATES = ["unknown", "partial", "clear", "disputed", "validated", "stale"] as const;
export type CoverageState = (typeof COV_STATES)[number];

export const FALLBACK = "#8a8f9c";
export const nodeRadius = (deg: number) => 2 + Math.min(7, deg * 0.3);
export const endId = (e: NodeId | GNode): NodeId => (typeof e === "object" ? e.id : e);

// Full circle in radians — shared by every canvas arc.
export const TAU = Math.PI * 2;

// Stable dedup key for an edge (source-target-predicate).
export const linkKey = (l: GLink): string => `${endId(l.source)}-${endId(l.target)}-${l.predicate}`;

export function hexToRgba(hex: string, a: number): string {
  let m = hex.replace("#", "");
  if (m.length === 3) m = m[0] + m[0] + m[1] + m[1] + m[2] + m[2]; // #rgb → #rrggbb
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

// Convert a resolved rgb()/rgba() string (from getComputedStyle) OR a hex to rgba
// with the given alpha — the coverage colors arrive as computed rgb().
export function toRgba(color: string, a: number): string {
  if (color.startsWith("#")) return hexToRgba(color, a);
  const m = color.match(/rgba?\(([^)]+)\)/);
  if (!m) return color;
  const [r, g, b] = m[1].split(",").map((s) => s.trim());
  return `rgba(${r},${g},${b},${a})`;
}
