"use client";

import { useEffect, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";
import { meterPercent, money } from "@/lib/format";

type MapNode = { id: string; column: string; kind: string; label: string; data: Record<string, unknown> };
type MapEdge = { source: string; target: string; label: string };
type Graph = {
  nodes: MapNode[];
  edges: MapEdge[];
  replay: Array<Record<string, unknown>>;
  active?: boolean;
  status?: string;
};

const COLORS: Record<string, string> = {
  contract: "#0f172a",
  clause: "#1f3a5f",
  threshold_rebate: "#b45309",
  price_match: "#0f766e",
  volume_discount: "#7c3aed",
  payment_terms: "#0369a1",
  renewal_notice: "#be123c",
  sla_penalty: "#c2410c",
  natural_language: "#4338ca",
  finding: "#b91c1c",
};

const LEGEND: Array<[string, string]> = [
  ["contract", "Agreement"],
  ["clause", "Clause"],
  ["threshold_rebate", "Rebate rule"],
  ["price_match", "Price rule"],
  ["volume_discount", "Discount rule"],
  ["payment_terms", "Payment rule"],
  ["renewal_notice", "Renewal rule"],
  ["sla_penalty", "SLA rule"],
  ["natural_language", "Language rule"],
  ["finding", "Finding"],
];

const NAMES: Record<string, string> = {
  contract: "Agreement",
  clause: "Clause",
  threshold_rebate: "Rebate",
  price_match: "Price",
  volume_discount: "Discount",
  payment_terms: "Payment terms",
  renewal_notice: "Renewal",
  sla_penalty: "SLA",
  natural_language: "Language rule",
  finding: "Finding",
};

const FIELDS: Record<string, Array<{ field: string; label: string; options?: string[] }>> = {
  threshold_rebate: [
    { field: "threshold_amount", label: "Threshold" },
    { field: "rate", label: "Rate" },
    {
      field: "application",
      label: "Application",
      options: ["incremental_above_threshold", "all_eligible_once_crossed", "rate_on_each_invoice_once_crossed"],
    },
  ],
  price_match: [
    { field: "sku", label: "SKU" },
    { field: "contracted_price", label: "Contracted price" },
  ],
  payment_terms: [
    { field: "discount_percent", label: "Discount rate" },
    { field: "discount_days", label: "Discount days" },
    { field: "net_days", label: "Net days" },
  ],
  renewal_notice: [
    { field: "notice_days", label: "Notice days" },
    { field: "expiry", label: "Expiry" },
  ],
  sla_penalty: [
    { field: "target", label: "Target" },
    { field: "penalty_rate", label: "Penalty rate" },
  ],
};

function EngineNode({ data }: NodeProps) {
  const color = String(data.color || "#1f3a5f");
  return (
    <div className="engine-node">
      <Handle type="target" position={Position.Left} className="engine-handle" />
      <span className="engine-dot" style={{ background: color }} />
      <span>
        <span className="engine-kicker">{String(data.kicker || "")}</span>
        <span className="engine-title">{String(data.title || "")}</span>
      </span>
      <Handle type="source" position={Position.Right} className="engine-handle" />
    </div>
  );
}

const nodeTypes = { engine: EngineNode };
const noSpotlight: string[] = [];

function titleFor(node: MapNode): string {
  if (node.kind === "finding") return money(node.label);
  if (node.kind === "clause") return String(node.data.heading || node.label);
  return NAMES[node.kind] || node.label;
}

export function RuleGraph({ documentId, refreshKey = 0, live = false, spotlight = noSpotlight }: { documentId: string; refreshKey?: number; live?: boolean; spotlight?: string[] }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [cursor, setCursor] = useState(0);
  const [hover, setHover] = useState<MapNode | null>(null);
  const [hoverAt, setHoverAt] = useState<{ x: number; y: number } | null>(null);
  const hideHoverTimer = useRef<number | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<MapNode | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [layingOut, setLayingOut] = useState(true);
  const [focusIds, setFocusIds] = useState<string[]>([]);
  const flowRef = useRef<ReactFlowInstance | null>(null);

  useEffect(() => {
    api<Graph>(`/v1/contracts/${documentId}/control-map`).then((body) => {
      setGraph(body);
      setCursor(body.replay.length);
    }).catch(() => {
      setGraph(null);
      setLayingOut(false);
    });
  }, [documentId, refreshKey]);

  useEffect(() => {
    if (!graph) return;
    let cancelled = false;
    setLayingOut(true);
    const replay = graph.replay.slice(0, cursor);
    const seen = new Set(replay.map((row) => String(row.transaction_id)));
    const showAll = cursor >= graph.replay.length;
    const watched = new Set(spotlight);
    const leakPairs = new Set(
      live
        ? replay
            .filter((row) => row.outcome === "violation" && (watched.size === 0 || watched.has(String(row.transaction_id))))
            .map((row) => `${String(row.transaction_id)}|${String(row.rule_id)}`)
        : [],
    );
    const leakRules = new Set([...leakPairs].map((pair) => `rule:${pair.split("|")[1]}`));
    const clauseIds = new Set(graph.edges.filter((edge) => leakRules.has(edge.target)).map((edge) => edge.source));
    const findingLeaks = (findingId: string) => {
      const finding = graph.nodes.find((node) => node.id === findingId);
      const tx = String(finding?.data.transaction_id || "");
      return graph.edges.some((edge) => edge.target === findingId && leakPairs.has(`${tx}|${edge.source.replace(/^rule:/, "")}`));
    };
    const flowing = (edge: MapEdge) => {
      if (leakPairs.size === 0) return false;
      if (leakRules.has(edge.target) || (edge.source.startsWith("contract:") && clauseIds.has(edge.target))) return true;
      return leakRules.has(edge.source) && edge.target.startsWith("finding:") && findingLeaks(edge.target);
    };
    const leaking = (node: MapNode) => {
      if (leakPairs.size === 0) return false;
      if (leakRules.has(node.id)) return true;
      return node.kind === "finding" && findingLeaks(node.id);
    };
    const visible = graph.nodes.filter((node) => node.kind !== "finding" || showAll || seen.has(String(node.data.transaction_id || "")));
    const ids = new Set(visible.map((node) => node.id));
    const visibleEdges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    const elkNodes = visible.map((node) => ({
      id: node.id,
      position: { x: 0, y: 0 },
      type: "engine",
      className: leaking(node) ? "leak" : undefined,
      data: {
        ...node.data,
        kicker: NAMES[node.kind] || node.column,
        title: titleFor(node),
        color: COLORS[node.kind] || "#1f3a5f",
        source: node,
      },
    }));
    import("elkjs/lib/elk.bundled.js").then(({ default: ELK }) => {
      const elk = new ELK();
      return elk.layout({
        id: "root",
        layoutOptions: {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.aspectRatio": "2.6",
          "elk.spacing.nodeNode": "18",
          "elk.layered.spacing.nodeNodeBetweenLayers": "72",
          "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
          "elk.layered.compaction.postCompaction.strategy": "EDGE_LENGTH",
        },
        children: elkNodes.map((node) => ({ id: node.id, width: 210, height: 52 })),
        edges: visibleEdges.map((edge, index) => ({ id: `e-${index}`, sources: [edge.source], targets: [edge.target] })),
      });
    }).then((laid) => {
      if (cancelled || !laid?.children) return;
      const positions = new Map(laid.children.map((child) => [child.id, child]));
      const focus = live ? visible.filter(leaking).map((node) => node.id) : [];
      setFocusIds(focus);
      setNodes(
        elkNodes.map((node) => {
          const next = positions.get(node.id);
          return { ...node, position: { x: next?.x ?? 0, y: next?.y ?? 0 } };
        }),
      );
      setEdges(
        visibleEdges.map((edge, index) => {
          const flow = flowing(edge);
          return {
            id: `e-${index}`,
            source: edge.source,
            target: edge.target,
            label: edge.label,
            type: "smoothstep",
            className: flow ? "flowing" : undefined,
            style: flow
              ? { stroke: "#dc2626", strokeWidth: 2.2, strokeDasharray: "8 6" }
              : { stroke: "#94a3b8", strokeWidth: 1.5 },
            markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: flow ? "#dc2626" : "#94a3b8" },
          };
        }),
      );
    }).catch(() => {
      if (!cancelled) setLayingOut(false);
    });
    return () => {
      cancelled = true;
    };
  }, [graph, cursor, live, spotlight]);

  const nodesRef = useRef(nodes);
  const focusRef = useRef(focusIds);
  nodesRef.current = nodes;
  focusRef.current = focusIds;

  function frameView(flow: ReactFlowInstance) {
    const targets = nodesRef.current.filter((node) => focusRef.current.includes(node.id));
    if (nodesRef.current.length === 0) return;
    if (live && targets.length) {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const node of targets) {
        const width = node.measured?.width ?? 210;
        const height = node.measured?.height ?? 52;
        minX = Math.min(minX, node.position.x);
        minY = Math.min(minY, node.position.y);
        maxX = Math.max(maxX, node.position.x + width);
        maxY = Math.max(maxY, node.position.y + height);
      }
      const pane = paneRef.current?.getBoundingClientRect();
      const zoomX = pane ? (pane.width - 72) / Math.max(maxX - minX, 1) : 1;
      const zoomY = pane ? (pane.height - 72) / Math.max(maxY - minY, 1) : 1;
      const zoom = Math.min(1.45, Math.min(zoomX, zoomY));
      flow.setCenter((minX + maxX) / 2, (minY + maxY) / 2, { zoom, duration: 800 });
    } else {
      flow.fitView({ padding: 0.16, duration: 400 });
    }
    setLayingOut(false);
  }

  useEffect(() => {
    const flow = flowRef.current;
    if (!flow || nodes.length === 0) return;
    const first = window.setTimeout(() => frameView(flow), 140);
    const second = window.setTimeout(() => {
      if (live && focusRef.current.length) frameView(flow);
    }, 520);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(second);
    };
  }, [nodes, focusIds, live]);

  function cancelHideHover() {
    if (hideHoverTimer.current != null) {
      window.clearTimeout(hideHoverTimer.current);
      hideHoverTimer.current = null;
    }
  }

  function hideHoverSoon() {
    cancelHideHover();
    hideHoverTimer.current = window.setTimeout(() => {
      setHover(null);
      setHoverAt(null);
    }, 220);
  }

  useEffect(() => () => cancelHideHover(), []);

  function openEditor(node: MapNode) {
    const fields = FIELDS[node.kind] || [];
    const next: Record<string, string> = {};
    for (const field of fields) {
      const key = field.field === "threshold_amount" ? "threshold" : field.field;
      const value = node.data[key];
      next[field.field] = value == null ? "" : String(value);
    }
    setDraft(next);
    setSelected(node);
  }

  async function saveRule() {
    if (!selected) return;
    const ruleId = selected.id.replace(/^rule:/, "");
    let note = "Rule updated. Run the tests again before approval.";
    for (const [field, value] of Object.entries(draft)) {
      if (!value) continue;
      const result = await api<{ live_kept: boolean }>(`/v1/contracts/${documentId}/rule-edit`, {
        method: "POST",
        body: JSON.stringify({ rule_id: ruleId, field, value }),
      });
      if (result.live_kept) note = "Saved on a new draft. The live engine keeps running until you approve it.";
    }
    setMessage(note);
    const body = await api<Graph>(`/v1/contracts/${documentId}/control-map`);
    setGraph(body);
  }

  const detail = hover?.data || {};
  const threshold = detail.threshold as string | null | undefined;
  const balance = detail.balance as string | undefined;

  return (
    <div className="flex h-full min-h-0 w-full flex-1 flex-col gap-2">
      <div className="flex items-center gap-4 text-sm shrink-0">
        <span className="text-stone-500">Replay</span>
        <input className="flex-1" type="range" min={0} max={graph?.replay.length || 0} value={cursor} onChange={(event) => setCursor(Number(event.target.value))} />
        <span className="tabular-nums text-stone-500">{cursor} / {graph?.replay.length || 0}</span>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-600 max-w-[52%]">
          {LEGEND.map(([kind, label]) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span className="engine-dot" style={{ background: COLORS[kind] }} />
              {label}
            </span>
          ))}
        </div>
      </div>
      <div ref={paneRef} className="relative flex-1 min-h-0 panel overflow-hidden">
      {layingOut && (
        <div className="absolute inset-0 z-30 grid place-items-center bg-paper/80">
          <p className="text-sm text-stone-600 flex items-center gap-2"><span className="spinner" /> Laying out the graph</p>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={(instance) => {
          flowRef.current = instance;
          window.setTimeout(() => frameView(instance), 90);
        }}
        onNodeMouseEnter={(event, node) => {
          cancelHideHover();
          const source = (node.data.source as MapNode) || null;
          const pane = paneRef.current?.getBoundingClientRect();
          const host = (event.target as HTMLElement).closest(".react-flow__node")?.getBoundingClientRect();
          if (!source || !pane || !host) {
            setHover(source);
            setHoverAt(null);
            return;
          }
          const cardWidth = 320;
          const cardHeight = 220;
          let x = host.right - pane.left + 10;
          let y = host.top - pane.top;
          if (x + cardWidth > pane.width - 8) x = host.left - pane.left - cardWidth - 10;
          if (x < 8) x = 8;
          if (y + cardHeight > pane.height - 8) y = Math.max(8, pane.height - cardHeight - 8);
          if (y < 8) y = 8;
          setHover(source);
          setHoverAt({ x, y });
        }}
        onNodeMouseLeave={hideHoverSoon}
        onNodeClick={(_event, node) => {
          const source = node.data.source as MapNode;
          if (source && FIELDS[source.kind]) openEditor(source);
        }}
      >
        <Background gap={18} color="#e6e2da" />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
      {hover && hoverAt && (
        <aside
          className="absolute z-10 w-80 max-h-[70%] overflow-auto overscroll-contain panel p-4 text-sm shadow-lg space-y-2"
          style={{ left: hoverAt.x, top: hoverAt.y }}
          onMouseEnter={cancelHideHover}
          onMouseLeave={hideHoverSoon}
        >
          <div className="text-xs uppercase tracking-wide text-slate-500">{NAMES[hover.kind] || hover.kind}</div>
          <div className="font-semibold">{titleFor(hover)}</div>
          {detail.clause_text ? <p className="text-slate-600 whitespace-pre-wrap max-h-32 overflow-auto">{String(detail.clause_text)}</p> : null}
          {detail.heading ? <p className="text-slate-600 whitespace-pre-wrap max-h-32 overflow-auto">{String(detail.text || "")}</p> : null}
          {threshold ? (
            <div>
              <div className="text-xs text-slate-500">Ledger {money(balance || 0)} of {money(threshold)}</div>
              <div className="mt-1 h-1.5 bg-slate-100 rounded">
                <div className="h-1.5 bg-accent rounded" style={{ width: `${meterPercent(balance || 0, threshold)}%` }} />
              </div>
            </div>
          ) : null}
          {detail.rate ? <div>Rate {String(detail.rate)} · {String(detail.application || "application unconfirmed")}</div> : null}
          {detail.sku ? <div>SKU {String(detail.sku)} at {money(String(detail.contracted_price || 0))}</div> : null}
          {detail.warned ? <div className="text-amber-800">Warning: {(detail.warning_reasons as string[] | undefined)?.join("; ") || `${detail.value_band} value, ${detail.risk_band} risk`}</div> : null}
          {detail.human_required ? <div>A person must confirm violations of this clause.</div> : null}
          {detail.explanation ? <div>{String(detail.explanation)}</div> : null}
          {detail.formula ? <div className="text-xs text-slate-500">{String(detail.formula)}</div> : null}
          {hover.kind === "finding" ? <div>{money(hover.label)} · {String(detail.status)} · {String(detail.transaction_id)}</div> : null}
        </aside>
      )}
      {selected && (
        <form
          className="absolute z-20 left-4 bottom-4 w-80 panel p-4 shadow-lg space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            saveRule().catch(() => setMessage(""));
          }}
        >
          <div className="flex justify-between items-center">
            <div className="font-semibold">Edit {titleFor(selected)}</div>
            <button type="button" className="text-xs text-slate-500" onClick={() => setSelected(null)}>Close</button>
          </div>
          {(FIELDS[selected.kind] || []).map((field) => (
            <label key={field.field} className="block text-xs text-slate-500">
              {field.label}
              {field.options ? (
                <select className="field mt-1" value={draft[field.field] || ""} onChange={(event) => setDraft({ ...draft, [field.field]: event.target.value })}>
                  <option value="">Select</option>
                  {field.options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}
                </select>
              ) : (
                <input className="field mt-1" value={draft[field.field] || ""} onChange={(event) => setDraft({ ...draft, [field.field]: event.target.value })} />
              )}
            </label>
          ))}
          <button className="btn btn-primary" type="submit">Save rule</button>
          {message && <p className="text-xs text-slate-600">{message}</p>}
        </form>
      )}
      </div>
    </div>
  );
}
