import { nodeRadius, toRgba, TAU, type GNode, type NodeId } from "./graphTypes";

// Multi-select ring: ice-blue, deliberately outside the coverage palette and ≠ the
// white focal ring.
const SEL_RING = "#a0c8ff";

export interface DrawOpts {
  palette: { nodeHot: string; text: string; fallback: string };
  selectedIds: ReadonlySet<NodeId>;
  selId: NodeId | undefined;
  nodeSize: number; // user multiplier (tune panel)
  labelZoom: number; // labels appear above this zoom (tune panel)
}

// Per-node canvas paint. Pure draw; ForceGraph2D doesn't save/restore so we do.
// Node color encodes COVERAGE STATE (resolved onto node.color by the view).
export function drawNode(node: GNode, ctx: CanvasRenderingContext2D, globalScale: number, opts: DrawOpts): void {
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  const color = node.hot ? opts.palette.nodeHot : node.color ?? opts.palette.fallback;
  const r = nodeRadius(node.degree) * opts.nodeSize;
  const gr = r * (node.hot ? 3.2 : 2.1);
  ctx.save();
  const g = ctx.createRadialGradient(x, y, 0, x, y, gr);
  g.addColorStop(0, color);
  g.addColorStop(0.45, toRgba(color, node.hot ? 0.42 : 0.3));
  g.addColorStop(1, "transparent");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, gr, 0, TAU);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, TAU);
  ctx.fill();
  if (node.fx != null) {
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(x + r + 1 / globalScale, y - r - 1 / globalScale, 1.6 / globalScale, 0, TAU);
    ctx.fill();
  }
  // multi-select ring (ice-blue) — distinct from the focal white ring
  if (opts.selectedIds.has(node.id)) {
    ctx.strokeStyle = SEL_RING;
    ctx.lineWidth = 2 / globalScale;
    ctx.beginPath();
    ctx.arc(x, y, r + 4 / globalScale, 0, TAU);
    ctx.stroke();
  }
  if (node.id === opts.selId) {
    ctx.strokeStyle = "#ffffff";
    ctx.globalAlpha = 0.7;
    ctx.lineWidth = 1.4 / globalScale;
    ctx.beginPath();
    ctx.arc(x, y, r + 3 / globalScale, 0, TAU);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  if (globalScale > opts.labelZoom) {
    ctx.font = `${11 / globalScale}px 'DM Mono', ui-monospace, monospace`;
    ctx.fillStyle = opts.palette.text;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(node.name, x + r + 3 / globalScale, y);
  }
  ctx.restore();
}
