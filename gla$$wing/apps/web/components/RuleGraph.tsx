"use client";

import { useEffect, useState } from "react";
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
  clause: "#1d4ed8",
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
  const color = String(data.color || "#1d4ed8");
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

function titleFor(node: MapNode): string {
  if (node.kind === "finding") return money(node.label);
  if (node.kind === "clause") return String(node.data.heading || node.label);
  return NAMES[node.kind] || node.label;
}

export function RuleGraph({ documentId, refreshKey = 0, live = false }: { documentId: string; refreshKey?: number; live?: boolean }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [cursor, setCursor] = useState(0);
  const [hover, setHover] = useState<MapNode | null>(null);
  const [selected, setSelected] = useState<MapNode | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");

  useEffect(() => {
    api<Graph>(`/v1/contracts/${documentId}/control-map`).then((body) => {
      setGraph(body);
      setCursor(body.replay.length);
    }).catch(() => setGraph(null));
  }, [documentId, refreshKey]);

  useEffect(() => {
    if (!graph) return;
    let cancelled = false;
    const replay = graph.replay.slice(0, cursor);
    const seen = new Set(replay.map((row) => String(row.transaction_id)));
    const showAll = cursor >= graph.replay.length;
    const leakPairs = new Set(
      live
        ? replay.filter((row) => row.outcome === "violation").map((row) => `${String(row.transaction_id)}|${String(row.rule_id)}`)
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
        color: COLORS[node.kind] || "#1d4ed8",
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
          "elk.spacing.nodeNode": "36",
          "elk.layered.spacing.nodeNodeBetweenLayers": "90",
        },
        children: elkNodes.map((node) => ({ id: node.id, width: 210, height: 52 })),
        edges: visibleEdges.map((edge, index) => ({ id: `e-${index}`, sources: [edge.source], targets: [edge.target] })),
      });
    }).then((laid) => {
      if (cancelled || !laid?.children) return;
      const positions = new Map(laid.children.map((child) => [child.id, child]));
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
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [graph, cursor, live]);

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
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <span className="text-slate-500">Replay</span>
        <input type="range" min={0} max={graph?.replay.length || 0} value={cursor} onChange={(event) => setCursor(Number(event.target.value))} />
        <span>{cursor} / {graph?.replay.length || 0}</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600">
        {LEGEND.map(([kind, label]) => (
          <span key={kind} className="inline-flex items-center gap-1.5">
            <span className="engine-dot" style={{ background: COLORS[kind] }} />
            {label}
          </span>
        ))}
      </div>
      <div className="relative h-[68vh] min-h-[520px] panel overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        onNodeMouseEnter={(_event, node) => setHover((node.data.source as MapNode) || null)}
        onNodeClick={(_event, node) => {
          const source = node.data.source as MapNode;
          if (source && FIELDS[source.kind]) openEditor(source);
        }}
      >
        <Background gap={18} color="#e2e8f0" />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
      {hover && (
        <aside className="absolute z-10 right-4 top-16 w-80 panel p-4 text-sm shadow-lg space-y-2">
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
