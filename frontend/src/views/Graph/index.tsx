import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useSearchParams } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { GlassCard } from "../../components/GlassCard";
import { SafeText } from "../../components/SafeText";
import { CorroborationBadge } from "../../components/CorroborationBadge";
import { DisputeBadge } from "../../components/DisputeBadge";
import { SensitivityBadge } from "../../components/SensitivityBadge";
import { TrustTierBadge } from "../../components/TrustTierBadge";
import { CoverageStateBadge } from "../../components/CoverageStateBadge";
import { pushToast } from "../../lib/toast";
import { get } from "../../lib/api";
import { useCoverage } from "../../hooks/useCoverage";
import { useMe } from "../../hooks/useScore";
import { useKnowledgeStats } from "../../hooks/useDashboard";
import { useMergeEntities } from "../../hooks/useOntology";
import { useGraphAll, useGraphSubgraph, useGraphSearch, useEntityClaims, type SubgraphResponse } from "../../hooks/useGraph";
import { COV_STATES, FALLBACK, nodeRadius, endId, linkKey, toRgba, TAU, type GNode, type GLink, type NodeId, type FgHandle } from "../../components/graph/graphTypes";
import { drawNode } from "../../components/graph/drawNode";
import { GraphContextMenu } from "../../components/graph/ContextMenu";
import { MergeConfirmModal } from "../../components/graph/MergeConfirmModal";
import { TunePanel, type TuneValues } from "../../components/graph/TunePanel";

const PROJECT_ID = 1;
const ACCENT = "var(--sec-graph)";

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

// Resolve a CSS-var expression to a concrete color (a canvas can't read vars).
function resolveColor(expr: string): string {
  const el = document.createElement("span");
  el.style.color = expr;
  el.style.display = "none";
  document.body.appendChild(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c || FALLBACK;
}

// Graph screen is ALWAYS dark, both themes (§2.7). Nodes colored by COVERAGE STATE.
export function GraphView() {
  const me = useMe();
  const isAdmin = Boolean(me.data?.is_super || me.data?.is_ceo);
  const knowledge = useKnowledgeStats();
  const coverage = useCoverage(PROJECT_ID);
  const merge = useMergeEntities();

  const [center, setCenter] = useState("");
  const [depth, setDepth] = useState(2);
  const [full, setFull] = useState(true); // whole-graph until a default center resolves
  const [selected, setSelected] = useState<GNode | null>(null);
  const [hoveredId, setHoveredId] = useState<NodeId | undefined>(undefined);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<NodeId>>(new Set());
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; node: GNode | null } | null>(null);
  const [selectionBox, setSelectionBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [mergeConfirm, setMergeConfirm] = useState<{ source: GNode; target: GNode } | null>(null);
  const [extra, setExtra] = useState<{ nodes: GNode[]; links: GLink[] }>({ nodes: [], links: [] });
  const [expanding, setExpanding] = useState(false);
  const [shiftHeld, setShiftHeld] = useState(false);
  const [tuneOpen, setTuneOpen] = useState(false);
  const [tune, setTune] = useState<TuneValues>({ charge: -60, linkDist: 40, nodeSize: 1, labelZoom: 1.6 });
  const [frozen, setFrozen] = useState(false);
  const [, setPinTick] = useState(0);
  const fittedRef = useRef(false);

  const subQ = useGraphSubgraph(center, depth, !full);
  const allQ = useGraphAll(full);
  const q = full ? allQ : subQ;

  // ⌘K / palette can deep-link an entity to center via ?center=.
  const [searchParams] = useSearchParams();
  const urlCenter = searchParams.get("center");
  useEffect(() => {
    if (urlCenter) {
      setCenter(urlCenter);
      setFull(false);
    }
  }, [urlCenter]);

  const defaultCenter = knowledge.data?.top_entities_by_degree?.[0]?.name;

  // entity name → coverage_state, for node coloring + the inspector badge.
  const stateByEntity = useMemo(() => {
    const m = new Map<string, string>();
    coverage.data?.entities.forEach((e) => m.set(e.entity_name, e.coverage_state));
    return m;
  }, [coverage.data]);

  // Resolve palette once (screen is dark regardless of theme; coverage vars are
  // theme-independent).
  const palette = useMemo(() => {
    const cov: Record<string, string> = {};
    COV_STATES.forEach((s) => (cov[s] = resolveColor(`var(--cov-${s})`)));
    return {
      cov,
      fallback: resolveColor("var(--ink-4)"),
      nodeHot: resolveColor("var(--node-hot)"),
      text: resolveColor("var(--screen-text)"),
      edge: resolveColor("var(--edge)"),
    };
  }, []);

  const colorForNode = useCallback(
    (name: string) => palette.cov[stateByEntity.get(name) ?? ""] ?? palette.fallback,
    [palette, stateByEntity],
  );

  // Once the default center (top entity by degree) resolves, focus it. Falls back
  // to whole-graph mode if knowledge is unavailable (non-admin 403).
  useEffect(() => {
    if (defaultCenter && !center) {
      setCenter(defaultCenter);
      setFull(false);
    }
  }, [defaultCenter, center]);

  const wrapRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<FgHandle | undefined>(undefined);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Track Shift so the box-select overlay intercepts pointer events only when held.
  useEffect(() => {
    const down = (e: KeyboardEvent) => e.key === "Shift" && setShiftHeld(true);
    const up = (e: KeyboardEvent) => e.key === "Shift" && setShiftHeld(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  // Escape dismisses context-menu / merge confirm / tune panel.
  useEffect(() => {
    if (!contextMenu && !mergeConfirm && !tuneOpen) return;
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setContextMenu(null);
        setMergeConfirm(null);
        setTuneOpen(false);
      }
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [contextMenu, mergeConfirm, tuneOpen]);

  // Base data → fresh cloned GNode/GLink (react-force-graph mutates in place, so we
  // never hand it the query cache). Coverage color resolved per node.
  const baseData = useMemo(() => {
    const nodes: GNode[] = (q.data?.nodes ?? []).map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      degree: n.degree,
      coverage_state: stateByEntity.get(n.name),
      color: colorForNode(n.name),
      hot: n.name === center,
    }));
    const links: GLink[] = (q.data?.edges ?? []).map((e) => ({ source: endId(e.source), target: endId(e.target), predicate: e.predicate }));
    return { nodes, links };
  }, [q.data, center, colorForNode, stateByEntity]);

  // Merge expanded 1-hop neighbors into the base, deduped by id + edge key.
  const data = useMemo(() => {
    if (extra.nodes.length === 0 && extra.links.length === 0) return baseData;
    const nodeMap = new Map<NodeId, GNode>();
    for (const n of baseData.nodes) nodeMap.set(n.id, n);
    for (const n of extra.nodes) if (!nodeMap.has(n.id)) nodeMap.set(n.id, n);
    const seen = new Set(baseData.links.map(linkKey));
    const links = [...baseData.links];
    for (const l of extra.links) {
      const k = linkKey(l);
      if (!seen.has(k)) {
        links.push(l);
        seen.add(k);
      }
    }
    return { nodes: [...nodeMap.values()], links };
  }, [baseData, extra]);

  // Adjacency (node id → set of directly connected node ids) for the hover
  // highlight. Rebuilt only when the edge set changes.
  const adjacency = useMemo(() => {
    const m = new Map<NodeId, Set<NodeId>>();
    for (const l of data.links) {
      const s = endId(l.source);
      const t = endId(l.target);
      (m.get(s) ?? m.set(s, new Set()).get(s)!).add(t);
      (m.get(t) ?? m.set(t, new Set()).get(t)!).add(s);
    }
    return m;
  }, [data.links]);
  const connectedIds = useMemo(() => (hoveredId != null ? adjacency.get(hoveredId) : undefined), [adjacency, hoveredId]);

  // Apply tune forces + reheat on change / new dataset.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength?.(tune.charge);
    fg.d3Force("link")?.distance?.(tune.linkDist);
    fg.d3ReheatSimulation();
  }, [tune.charge, tune.linkDist, data]);

  const truncated = full ? (allQ.data ? allQ.data.node_count > allQ.data.nodes.length : false) : subQ.data?.truncated;
  const shownCount = full ? allQ.data?.nodes.length ?? data.nodes.length : subQ.data?.shown_nodes ?? data.nodes.length;
  const totalCount: number | string = full ? allQ.data?.node_count ?? "—" : subQ.data?.total_nodes ?? "—";
  const selId = selected?.id;

  const nodeCanvasObject = useCallback(
    (n: object, ctx: CanvasRenderingContext2D, globalScale: number) => drawNode(n as GNode, ctx, globalScale, { palette, selectedIds, selId, nodeSize: tune.nodeSize, labelZoom: tune.labelZoom, hoveredId, connectedIds }),
    [palette, selectedIds, selId, tune.nodeSize, tune.labelZoom, hoveredId, connectedIds],
  );

  // Dim edges not incident to the hovered node so the neighborhood reads clearly.
  const linkColor = useCallback(
    (l: object) => {
      if (hoveredId == null) return palette.edge;
      const link = l as GLink;
      const incident = endId(link.source) === hoveredId || endId(link.target) === hoveredId;
      return incident ? palette.nodeHot : toRgba(palette.edge, 0.06);
    },
    [hoveredId, palette.edge, palette.nodeHot],
  );

  const nodePointerAreaPaint = useCallback(
    (n: object, color: string, ctx: CanvasRenderingContext2D) => {
      const node = n as GNode;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, nodeRadius(node.degree) * tune.nodeSize + 3, 0, TAU);
      ctx.fill();
    },
    [tune.nodeSize],
  );

  // Re-fit + reset interaction state when the dataset (center/depth/full) changes.
  const autoSelectedFor = useRef<string | null>(null);
  useEffect(() => {
    fittedRef.current = false;
    setFrozen(false);
    autoSelectedFor.current = null;
    setSelectedIds(new Set());
    setExtra({ nodes: [], links: [] });
    setContextMenu(null);
    setMergeConfirm(null);
  }, [center, depth, full]);

  // Inspector follows the focal (center) node on load.
  useEffect(() => {
    if (data.nodes.length && center && autoSelectedFor.current !== center) {
      const c = data.nodes.find((n) => n.name === center);
      if (c) {
        setSelected(c);
        autoSelectedFor.current = center;
      }
    }
  }, [data, center]);

  const recenter = (node: GNode) => {
    setSelected(node);
    setFull(false);
    if (node.name && node.name !== center) setCenter(node.name);
  };

  const toggleSelect = (id: NodeId) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const expandNeighbors = async (node: GNode) => {
    if (expanding) return;
    setContextMenu(null);
    setExpanding(true);
    try {
      const sub = await get<SubgraphResponse>(`/graph/subgraph?center=${encodeURIComponent(node.name)}&depth=1`);
      const newNodes: GNode[] = (sub.nodes ?? []).map((n) => ({ id: n.id, name: n.name, type: n.type, degree: n.degree, coverage_state: stateByEntity.get(n.name), color: colorForNode(n.name) }));
      const newLinks: GLink[] = (sub.edges ?? []).map((e) => ({ source: endId(e.source), target: endId(e.target), predicate: e.predicate }));
      setExtra((prev) => {
        const haveNodes = new Set([...baseData.nodes, ...prev.nodes].map((n) => n.id));
        const haveLinks = new Set([...baseData.links, ...prev.links].map(linkKey));
        const addNodes = newNodes.filter((n) => !haveNodes.has(n.id));
        const addLinks = newLinks.filter((l) => !haveLinks.has(linkKey(l)));
        if (addNodes.length === 0 && addLinks.length === 0) return prev;
        return { nodes: [...prev.nodes, ...addNodes], links: [...prev.links, ...addLinks] };
      });
      setFrozen(false);
    } catch (e) {
      pushToast(`Expand failed: ${errMsg(e)}`, { tone: "error" });
    } finally {
      setExpanding(false);
    }
  };

  const doMerge = (keepAlias: boolean) => {
    if (!mergeConfirm) return;
    merge.mutate(
      { source_node_id: Number(mergeConfirm.source.id), target_node_id: Number(mergeConfirm.target.id), keep_as_alias: keepAlias },
      {
        onSuccess: () => {
          pushToast(`Merged ${mergeConfirm.source.name} → ${mergeConfirm.target.name}`, { tone: "success" });
          setMergeConfirm(null);
          setSelectedIds(new Set());
        },
        onError: (e) => {
          pushToast(`Merge failed: ${errMsg(e)}`, { tone: "error" });
          setMergeConfirm(null);
        },
      },
    );
  };

  // ── Box-select overlay (active only while Shift is held) ──
  const boxStart = useRef<{ x: number; y: number } | null>(null);
  const localPoint = (e: ReactPointerEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    return { x: e.clientX - (rect?.left ?? 0), y: e.clientY - (rect?.top ?? 0) };
  };
  const onBoxDown = (e: ReactPointerEvent) => {
    if (e.button !== 0) return;
    const p = localPoint(e);
    boxStart.current = p;
    setSelectionBox({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onBoxMove = (e: ReactPointerEvent) => {
    if (!boxStart.current) return;
    const p = localPoint(e);
    setSelectionBox({ x0: boxStart.current.x, y0: boxStart.current.y, x1: p.x, y1: p.y });
  };
  const onBoxUp = (e: ReactPointerEvent) => {
    if (!boxStart.current) return;
    const start = boxStart.current;
    const end = localPoint(e);
    boxStart.current = null;
    setSelectionBox(null);
    const fg = fgRef.current;
    if (!fg) return;
    const dx = Math.abs(end.x - start.x);
    const dy = Math.abs(end.y - start.y);
    if (dx < 4 && dy < 4) {
      let hit: GNode | null = null;
      let best = Infinity;
      for (const n of data.nodes) {
        if (n.x == null || n.y == null) continue;
        const sc = fg.graph2ScreenCoords(n.x, n.y);
        const d = Math.hypot(sc.x - end.x, sc.y - end.y);
        const reach = Math.max(8, nodeRadius(n.degree) + 4);
        if (d <= reach && d < best) {
          best = d;
          hit = n;
        }
      }
      if (hit) toggleSelect(hit.id);
      return;
    }
    const minX = Math.min(start.x, end.x);
    const maxX = Math.max(start.x, end.x);
    const minY = Math.min(start.y, end.y);
    const maxY = Math.max(start.y, end.y);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const n of data.nodes) {
        if (n.x == null || n.y == null) continue;
        const sc = fg.graph2ScreenCoords(n.x, n.y);
        if (sc.x >= minX && sc.x <= maxX && sc.y >= minY && sc.y <= maxY) next.add(n.id);
      }
      return next;
    });
  };

  // Coverage legend with per-state counts.
  const covLegend = useMemo(() => {
    const c = new Map<string, number>();
    for (const n of data.nodes) c.set(n.coverage_state ?? "unknown", (c.get(n.coverage_state ?? "unknown") ?? 0) + 1);
    return COV_STATES.map((s) => ({ state: s, count: c.get(s) ?? 0 }));
  }, [data.nodes]);

  const otherSelected = contextMenu?.node ? [...selectedIds].filter((id) => id !== contextMenu.node!.id) : [];
  const mergeTarget = otherSelected.length === 1 ? data.nodes.find((n) => n.id === otherSelected[0]) ?? null : null;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 mt-1.5 flex items-end justify-between gap-4 px-0.5">
        <div>
          <h1 className="font-mono text-[19px] font-medium tracking-[0.01em] text-ink-1">Graph Studio</h1>
          <p className="mt-1.5 text-[12.5px] text-ink-3">Explore the knowledge graph — nodes colored by coverage state.</p>
        </div>
      </div>

      <div
        ref={wrapRef}
        onContextMenu={(e) => e.preventDefault()}
        className="relative min-h-0 flex-1 overflow-hidden rounded-lg"
        style={{ background: "var(--screen-bg)", boxShadow: "inset 0 2px 22px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(0,0,0,0.45)" }}
      >
        <div
          className="pointer-events-none absolute inset-0"
          style={{ backgroundImage: "linear-gradient(var(--screen-grid) 1px, transparent 1px), linear-gradient(90deg, var(--screen-grid) 1px, transparent 1px)", backgroundSize: "32px 32px" }}
        />

        {size.w > 0 && data.nodes.length > 0 && (
          <ForceGraph2D
            ref={fgRef as never}
            width={size.w}
            height={size.h}
            graphData={data}
            backgroundColor="rgba(0,0,0,0)"
            // VS-G1: force-graph defaults nodeLabel to the node's `name` and renders
            // it via the float-tooltip's innerHTML on hover. Return "" to disable the
            // built-in tooltip entirely — labels are painted on the canvas (drawNode).
            nodeLabel={() => ""}
            cooldownTime={15000}
            enablePanInteraction={!shiftHeld}
            onEngineStop={() => {
              if (!fittedRef.current) {
                fgRef.current?.zoomToFit(400, 60);
                fittedRef.current = true;
              }
              setFrozen(true);
            }}
            onNodeDrag={() => setFrozen(false)}
            onNodeDragEnd={(n: object) => {
              const node = n as GNode;
              node.fx = node.x;
              node.fy = node.y;
              setPinTick((p) => p + 1);
            }}
            onNodeRightClick={(n: object, ev: MouseEvent) => {
              ev.preventDefault();
              const rect = wrapRef.current?.getBoundingClientRect();
              setContextMenu({ x: ev.clientX - (rect?.left ?? 0), y: ev.clientY - (rect?.top ?? 0), node: n as GNode });
            }}
            onBackgroundRightClick={(ev: MouseEvent) => {
              ev.preventDefault();
              const rect = wrapRef.current?.getBoundingClientRect();
              setContextMenu({ x: ev.clientX - (rect?.left ?? 0), y: ev.clientY - (rect?.top ?? 0), node: null });
            }}
            onNodeClick={(n: object, ev: MouseEvent) => {
              if (ev?.shiftKey) toggleSelect((n as GNode).id);
              else recenter(n as GNode);
            }}
            onNodeHover={(n: object | null) => setHoveredId(n ? (n as GNode).id : undefined)}
            onBackgroundClick={() => {
              setSelected(null);
              setContextMenu(null);
            }}
            linkColor={linkColor}
            linkWidth={(l: object) => (hoveredId != null && (endId((l as GLink).source) === hoveredId || endId((l as GLink).target) === hoveredId) ? 1.4 : 0.6)}
            nodePointerAreaPaint={nodePointerAreaPaint}
            nodeCanvasObject={nodeCanvasObject}
          />
        )}

        {/* Box-select overlay — captures pointer events only while Shift is held. */}
        <div
          className="absolute inset-0"
          style={{ pointerEvents: shiftHeld ? "auto" : "none", cursor: shiftHeld ? "crosshair" : "default" }}
          onPointerDown={onBoxDown}
          onPointerMove={onBoxMove}
          onPointerUp={onBoxUp}
        >
          {selectionBox && (
            <div
              className="absolute"
              style={{
                left: Math.min(selectionBox.x0, selectionBox.x1),
                top: Math.min(selectionBox.y0, selectionBox.y1),
                width: Math.abs(selectionBox.x1 - selectionBox.x0),
                height: Math.abs(selectionBox.y1 - selectionBox.y0),
                background: "color-mix(in srgb, var(--sec-graph) 12%, transparent)",
                boxShadow: "inset 0 0 0 1px var(--sec-graph)",
              }}
            />
          )}
        </div>

        {truncated && (
          <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md px-3 py-1.5 font-mono text-[10px]" style={{ background: "color-mix(in srgb, var(--sec-setup) 18%, transparent)", color: "var(--screen-text)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-setup) 70%, transparent)" }}>
            Showing {shownCount} of {totalCount} nodes
          </div>
        )}

        {/* loading / empty / error over the dark screen */}
        {q.isPending && <Overlay>Loading graph…</Overlay>}
        {q.isError && (
          <Overlay>
            <div className="flex flex-col items-center gap-2">
              <span className="h-[7px] w-[7px] rounded-full" style={{ background: "var(--red)", boxShadow: "0 0 6px rgba(222,70,48,0.5)" }} />
              <span>Failed to load graph</span>
              <button type="button" onClick={() => void q.refetch()} className="font-mono text-[12px] underline underline-offset-2" style={{ color: palette.nodeHot }}>
                Retry
              </button>
            </div>
          </Overlay>
        )}
        {!q.isPending && !q.isError && data.nodes.length === 0 && <Overlay>No entities in the graph yet</Overlay>}

        {/* controls: hop + center + search + coverage legend + tune */}
        <div className="pointer-events-auto absolute left-4 top-4 flex w-[230px] flex-col gap-2.5">
          <div className="flex items-center gap-2 rounded-md px-2 py-1.5" style={{ background: "rgba(10,10,12,0.5)", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}>
            <span className="pl-1 font-mono text-[9.5px] uppercase tracking-[0.1em]" style={{ color: palette.text, opacity: 0.7 }}>Hops</span>
            <div className="flex gap-0.5">
              {[1, 2].map((d) => (
                <button key={d} type="button" onClick={() => { setFull(false); setDepth(d); }} className="h-[22px] w-[22px] rounded-sm font-mono text-[11px] tabular-nums transition-colors" style={!full && depth === d ? { background: "color-mix(in srgb, var(--sec-graph) 28%, transparent)", color: "var(--screen-text)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-graph) 45%, transparent)" } : { color: palette.text, background: "rgba(255,255,255,0.06)" }}>
                  {d}
                </button>
              ))}
              <button type="button" onClick={() => setFull(true)} className="h-[22px] rounded-sm px-2 font-mono text-[10px] uppercase tracking-[0.06em] transition-colors" style={full ? { background: "color-mix(in srgb, var(--sec-graph) 28%, transparent)", color: "var(--screen-text)", boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--sec-graph) 45%, transparent)" } : { color: palette.text, background: "rgba(255,255,255,0.06)" }}>
                Full
              </button>
            </div>
          </div>

          {center && (
            <div className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-mono text-[9.5px]" style={{ background: "rgba(10,10,12,0.5)", color: palette.text, boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}>
              <span className="uppercase tracking-[0.1em] opacity-60">Center</span>
              <span className="truncate" style={{ maxWidth: 150 }}>{center}</span>
            </div>
          )}

          <GraphSearch palette={palette} onSelect={(name) => recenter({ id: name, name, degree: 0 })} />

          {selectedIds.size > 0 && (
            <div className="flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 font-mono text-[9.5px]" style={{ background: "rgba(10,10,12,0.5)", color: palette.text, boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}>
              <span>{selectedIds.size} selected</span>
              <button type="button" onClick={() => setSelectedIds(new Set())} className="rounded-sm px-1.5 uppercase tracking-[0.08em]" style={{ background: "rgba(255,255,255,0.08)" }}>
                Clear
              </button>
            </div>
          )}

          <div className="flex flex-col gap-1 rounded-md px-2.5 py-2" style={{ background: "rgba(10,10,12,0.5)", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}>
            <span className="mb-0.5 font-mono text-[9px] uppercase tracking-[0.12em]" style={{ color: palette.text, opacity: 0.5 }}>Coverage</span>
            {covLegend.map(({ state, count }) => (
              <span key={state} className="flex items-center gap-1.5 font-mono text-[9.5px]" style={{ color: palette.text }}>
                <span className="h-[6px] w-[6px] flex-none rounded-full" style={{ background: palette.cov[state], boxShadow: `0 0 5px ${palette.cov[state]}` }} />
                <span className="flex-1">{state}</span>
                <span className="opacity-50">{count}</span>
              </span>
            ))}
          </div>

          <TunePanel open={tuneOpen} onToggle={() => setTuneOpen((o) => !o)} values={tune} onChange={(patch) => setTune((prev) => ({ ...prev, ...patch }))} />
        </div>

        {/* status slab */}
        <div className="pointer-events-none absolute bottom-4 left-4 flex items-center gap-2 rounded-md px-3 py-1.5 font-mono text-[10px]" style={{ background: "rgba(10,10,12,0.5)", color: palette.text, boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}>
          <span className="h-[7px] w-[7px] rounded-full" style={frozen ? { background: "var(--ink-4)" } : { background: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
          {frozen ? "frozen" : "live"} · {data.nodes.length} nodes
        </div>

        {contextMenu && (
          <GraphContextMenu
            menu={contextMenu}
            size={size}
            isAdmin={isAdmin}
            mergeTarget={mergeTarget}
            expanding={expanding}
            hasSelection={selectedIds.size > 0}
            onClose={() => setContextMenu(null)}
            onInspect={(node) => { setSelected(node); setContextMenu(null); }}
            onRecenter={(node) => { recenter(node); setContextMenu(null); }}
            onExpand={(node) => void expandNeighbors(node)}
            onMerge={(node, target) => { setMergeConfirm({ source: node, target }); setContextMenu(null); }}
            onSelectVisible={() => { setSelectedIds(new Set(data.nodes.map((n) => n.id))); setContextMenu(null); }}
            onClearSelection={() => { setSelectedIds(new Set()); setContextMenu(null); }}
          />
        )}

        {mergeConfirm && (
          <MergeConfirmModal source={mergeConfirm.source} target={mergeConfirm.target} pending={merge.isPending} onConfirm={doMerge} onCancel={() => setMergeConfirm(null)} />
        )}

        {selected && (
          <div className="pointer-events-auto absolute right-4 top-4 bottom-4 w-[320px]">
            <Inspector node={selected} state={stateByEntity.get(selected.name)} color={colorForNode(selected.name)} onClose={() => setSelected(null)} />
          </div>
        )}
      </div>
    </div>
  );
}

function Overlay({ children }: { children: React.ReactNode }) {
  return <div className="absolute inset-0 grid place-items-center font-mono text-[12.5px]" style={{ color: "var(--screen-text)" }}>{children}</div>;
}

// ── Search box (fuzzy /graph/search) ──────────────────────────────────────────
function GraphSearch({ palette, onSelect }: { palette: { text: string }; onSelect: (name: string) => void }) {
  const [q, setQ] = useState("");
  const { data: matches, isFetching } = useGraphSearch(q);
  return (
    <div className="rounded-md p-2" style={{ background: "rgba(10,10,12,0.5)", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" }}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search nodes…"
        className="w-full rounded-sm bg-transparent px-1 py-1 font-mono text-[11px] outline-none"
        style={{ color: palette.text }}
      />
      {q.trim() && (
        <ul className="mt-1 max-h-40 overflow-y-auto">
          {isFetching && <li className="px-1 py-1 font-mono text-[10px]" style={{ color: palette.text, opacity: 0.6 }}>Searching…</li>}
          {matches?.length === 0 && !isFetching && <li className="px-1 py-1 font-mono text-[10px]" style={{ color: palette.text, opacity: 0.6 }}>No matches</li>}
          {matches?.map((m) => (
            <li key={m.id}>
              <button type="button" onClick={() => { onSelect(m.name); setQ(""); }} className="block w-full truncate rounded px-1 py-1 text-left font-mono text-[11px] hover:bg-[rgba(255,255,255,0.06)]" style={{ color: palette.text }}>
                <SafeText text={m.name} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Inspector: entity meta + claims whose subject is this entity ──────────────
function Inspector({ node, state, color, onClose }: { node: GNode; state?: string; color: string; onClose: () => void }) {
  const { data: claims, isLoading, isError } = useEntityClaims(PROJECT_ID, node.name);
  const Cell = ({ k, v }: { k: string; v: string }) => (
    <div className="rounded-md p-2.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
      <div className="truncate font-mono text-[12.5px] text-ink-1">{v}</div>
      <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-3">{k}</div>
    </div>
  );
  return (
    <GlassCard className="flex h-full flex-col p-[18px]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-2">
            <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
            {node.type || "untyped"}
          </div>
          <div className="mt-2 break-words text-[16px] font-semibold leading-tight text-ink-1">
            <SafeText text={node.name} />
          </div>
          {state && (
            <div className="mt-1.5">
              <CoverageStateBadge state={state} />
            </div>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="grid h-[28px] w-[28px] flex-none place-items-center rounded-md text-ink-2 transition-colors hover:text-ink-1" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} width={14} height={14}><path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" /></svg>
        </button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <Cell k="Type" v={node.type || "untyped"} />
        <Cell k="Degree" v={String(node.degree)} />
      </div>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
        <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">Claims{claims ? ` · ${claims.length}` : ""}</div>
        {isLoading ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <span key={i} className="h-[36px] animate-pulse rounded-md" style={{ background: "var(--inset)" }} />
            ))}
          </div>
        ) : isError ? (
          <div className="font-mono text-[11.5px] text-ink-3">Couldn't load claims</div>
        ) : !claims || claims.length === 0 ? (
          <div className="font-mono text-[11.5px] text-ink-3">No claims for this entity</div>
        ) : (
          <ul className="flex flex-col gap-2">
            {claims.map((c) => (
              <li key={c.id} className="rounded-md p-2.5" style={{ background: "var(--inset)", boxShadow: "inset 0 0 0 1px var(--card-hairline)" }}>
                <div className="mb-1 font-body text-[12px] text-ink-1">
                  <SafeText text={c.object_value ?? c.object_entity ?? c.predicate} />
                </div>
                <div className="mb-1.5 font-mono text-[11px] leading-snug text-ink-2">
                  <SafeText text={c.evidence_text} />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <CorroborationBadge level={c.corroboration_level} />
                  {c.dispute_state !== "undisputed" && <DisputeBadge state={c.dispute_state} />}
                  <SensitivityBadge level={c.sensitivity} />
                  <TrustTierBadge tier={c.trust_tier} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </GlassCard>
  );
}
