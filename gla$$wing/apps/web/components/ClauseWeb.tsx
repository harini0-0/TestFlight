"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";

type Document = { id: string; index: number; kind: string; label: string; filename: string; title: string; clause_count: number };
type Clause = { id: string; clause_id: string; section: string; heading: string; text: string; commercial: boolean; document_index: number; document_id: string | null; outgoing: number; incoming: number };
type External = { id: string; label: string };
type Reference = {
  id: string;
  source: string;
  target: string;
  source_clause_id: string;
  target_index: number | null;
  target_clause_id: string | null;
  raw: string;
  kind: "specific" | "generic" | "external";
  resolved: boolean;
};
type Network = {
  supplier_key: string;
  documents: Document[];
  clauses: Clause[];
  external: External[];
  references: Reference[];
};
type PackFile = { document_id: string; kind: string; filename: string };
type Pack = { pack_id: string; files: PackFile[] };
type ImpactRule = { rule_id: string; rule_type: string; severity: string; warned: boolean; source_clause_ids: string[]; reason: string };
type Impact = {
  document_id: string;
  child_document_id: string;
  child_index: number;
  changed_clause_ids: string[];
  impacted_clause_ids: string[];
  impacted_rules: ImpactRule[];
  references: Reference[];
  external: External[];
};
type EditResult = { bundle_id: string; version: number; status: string; active: boolean; impact: Impact };

// Rebuild a child document's body from its clauses, applying the edit to one of
// them, so the backend re-segments to the same sections it started with.
function reconstructBody(clauses: Clause[], editedId: string, editedText: string): string {
  const ordered = [...clauses].sort((a, b) => a.section.localeCompare(b.section, undefined, { numeric: true }));
  return (
    ordered
      .map((clause) => {
        const text = (clause.id === editedId ? editedText : clause.text).trim();
        return clause.section === "0" ? text : `${clause.section}. ${text}`;
      })
      .join("\n\n") + "\n"
  );
}

const KIND_COLORS: Record<string, string> = {
  contract: "#0f172a",
  rebate: "#b45309",
  discount: "#7c3aed",
  sla: "#c2410c",
  renewal: "#be123c",
  payment_terms: "#0369a1",
  external: "#64748b",
  clause: "#1f3a5f",
};

const KIND_NAMES: Record<string, string> = {
  contract: "Contract",
  rebate: "Rebate",
  discount: "Discount",
  sla: "Service level",
  renewal: "Renewal",
  payment_terms: "Payment terms",
};

const REF_STYLE: Record<Reference["kind"], { stroke: string; dash?: string; label: string }> = {
  specific: { stroke: "#1f3a5f", label: "Names the document" },
  generic: { stroke: "#b45309", dash: "7 5", label: "Refers to that kind" },
  external: { stroke: "#94a3b8", dash: "2 5", label: "Outside this workspace" },
};

type Meta = { kind: string; role: "hub" | "clause" | "ext"; source?: Clause | Document | External; refs?: Reference[] };

function WebNode({ data }: NodeProps) {
  const meta = data as unknown as { color: string; title: string; kicker: string; role: "hub" | "clause" | "ext" };
  const hub = meta.role === "hub";
  const ext = meta.role === "ext";
  return (
    <div className={`clause-node ${hub ? "clause-node-hub" : ext ? "clause-node-ext" : "clause-node-spoke"}`} style={hub || ext ? { borderColor: meta.color } : undefined}>
      <Handle type="target" position={Position.Top} id="t" className="clause-handle" isConnectable={false} />
      {hub || ext ? <span className="clause-dot" style={{ background: meta.color }} /> : null}
      <span className="clause-node-body">
        <span className="clause-kicker">{meta.kicker}</span>
        <span className="clause-title">{meta.title}</span>
      </span>
      <Handle type="source" position={Position.Bottom} id="s" className="clause-handle" isConnectable={false} />
    </div>
  );
}

const nodeTypes = { web: WebNode };

export function ClauseWeb({ documentId }: { documentId: string }) {
  const [network, setNetwork] = useState<Network | null>(null);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [hover, setHover] = useState<Meta | null>(null);
  const [hoverAt, setHoverAt] = useState<{ x: number; y: number } | null>(null);
  const [files, setFiles] = useState<PackFile[]>([]);
  const [selected, setSelected] = useState<Clause | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [impact, setImpact] = useState<Impact | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const flowRef = useRef<ReactFlowInstance | null>(null);

  useEffect(() => {
    api<Network>(`/v1/contracts/${documentId}/clause-network`)
      .then(setNetwork)
      .catch(() => setError("This workspace has no processed engine yet. Process the documents first."));
    api<Pack>(`/v1/packs/${documentId}`)
      .then((pack) => setFiles(pack.files || []))
      .catch(() => setFiles([]));
  }, [documentId]);

  async function applyEdit() {
    if (!selected || !network) return;
    const doc = network.documents.find((item) => item.index === selected.document_index);
    const file = doc ? files.find((item) => item.filename === doc.filename) : undefined;
    if (!file) {
      setSaveError("Could not match this clause to a source document to edit.");
      return;
    }
    const docClauses = network.clauses.filter((item) => item.document_index === selected.document_index);
    const body = reconstructBody(docClauses, selected.id, draft);
    setSaving(true);
    setSaveError("");
    try {
      const result = await api<EditResult>(`/v1/contracts/${documentId}/clause-edit`, {
        method: "POST",
        body: JSON.stringify({ child_document_id: file.document_id, text: body, changed_sections: [selected.section] }),
      });
      const fresh = await api<Network>(`/v1/contracts/${documentId}/clause-network`);
      setNetwork(fresh);
      setImpact(result.impact);
      setSelected(null);
    } catch (err) {
      setSaveError(String((err as Error)?.message || err));
    } finally {
      setSaving(false);
    }
  }

  const refsBySource = useMemo(() => {
    const map = new Map<string, Reference[]>();
    for (const ref of network?.references || []) {
      const list = map.get(ref.source) || [];
      list.push(ref);
      map.set(ref.source, list);
    }
    return map;
  }, [network]);

  useEffect(() => {
    if (!network) return;
    const participating = new Set<string>();
    for (const ref of network.references) {
      participating.add(ref.source);
      if (ref.target.startsWith("clause:")) participating.add(ref.target);
    }
    const clauses = network.clauses.filter((clause) => showAll ? clause.commercial || participating.has(clause.id) : participating.has(clause.id));

    const ring: Array<{ id: string; color: string; kicker: string; title: string; role: "hub" | "ext"; meta: Meta }> = [
      ...network.documents.map((document) => ({
        id: document.id,
        color: KIND_COLORS[document.kind] || KIND_COLORS.clause,
        kicker: KIND_NAMES[document.kind] || document.kind,
        title: document.label,
        role: "hub" as const,
        meta: { kind: document.kind, role: "hub" as const, source: document },
      })),
      ...network.external.map((node) => ({
        id: node.id,
        color: KIND_COLORS.external,
        kicker: "External",
        title: node.label,
        role: "ext" as const,
        meta: { kind: "external", role: "ext" as const, source: node },
      })),
    ];

    const count = Math.max(ring.length, 1);
    const radius = Math.max(280, count * 74);
    const angleFor = new Map<string, number>();
    const placed: Node[] = ring.map((item, index) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / count;
      angleFor.set(item.id, angle);
      const width = 168;
      const height = 48;
      return {
        id: item.id,
        type: "web",
        position: { x: radius * Math.cos(angle) - width / 2, y: radius * Math.sin(angle) - height / 2 },
        data: { color: item.color, kicker: item.kicker, title: item.title, role: item.role, source: item.meta.source },
        draggable: true,
      };
    });

    const byDocument = new Map<number, Clause[]>();
    for (const clause of clauses) {
      const list = byDocument.get(clause.document_index) || [];
      list.push(clause);
      byDocument.set(clause.document_index, list);
    }
    const clauseNodes: Node[] = [];
    for (const [index, list] of byDocument) {
      const base = angleFor.get(`doc:${index}`) ?? 0;
      const step = 0.17;
      list.forEach((clause, position) => {
        const spread = (position - (list.length - 1) / 2) * step;
        const angle = base + spread;
        const ringOut = radius + 168;
        const width = 156;
        const height = 40;
        clauseNodes.push({
          id: clause.id,
          type: "web",
          position: { x: ringOut * Math.cos(angle) - width / 2, y: ringOut * Math.sin(angle) - height / 2 },
          data: {
            color: KIND_COLORS.clause,
            kicker: `§${clause.section}`,
            title: clause.heading || clause.clause_id,
            role: "clause",
            source: clause,
          },
          draggable: true,
        });
      });
    }

    const visible = new Set([...placed, ...clauseNodes].map((node) => node.id));
    const membership: Edge[] = clauseNodes
      .map((node) => {
        const clause = network.clauses.find((item) => item.id === node.id);
        const target = clause?.document_id;
        if (!target || !visible.has(target)) return null;
        return {
          id: `m-${node.id}`,
          source: node.id,
          target,
          sourceHandle: "s",
          targetHandle: "t",
          type: "straight",
          style: { stroke: "#e2e8f0", strokeWidth: 1 },
        } as Edge;
      })
      .filter((edge): edge is Edge => edge !== null);

    const referenceEdges: Edge[] = network.references
      .filter((ref) => visible.has(ref.source) && visible.has(ref.target))
      .map((ref) => {
        const style = REF_STYLE[ref.kind];
        return {
          id: ref.id,
          source: ref.source,
          target: ref.target,
          sourceHandle: "s",
          targetHandle: "t",
          type: "straight",
          label: ref.raw,
          labelBgStyle: { fill: "#f6f5f3" },
          labelStyle: { fontSize: 10, fill: "#57534e" },
          style: { stroke: style.stroke, strokeWidth: 2, strokeDasharray: style.dash },
          markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: style.stroke },
        } as Edge;
      });

    const changedIds = new Set((impact?.changed_clause_ids || []).map((cid) => `clause:${cid}`));
    const strandedIds = new Set((impact?.impacted_clause_ids || []).map((cid) => `clause:${cid}`));
    const impactPairs = new Set((impact?.references || []).map((ref) => `${ref.source}->${ref.target}`));
    const hasImpact = impact != null;

    const styledNodes = [...placed, ...clauseNodes].map((node) => {
      if (!hasImpact) return node;
      if (changedIds.has(node.id)) return { ...node, style: { outline: "3px solid #2563eb", outlineOffset: 2, borderRadius: 10 } };
      if (strandedIds.has(node.id)) return { ...node, style: { outline: "3px solid #dc2626", outlineOffset: 2, borderRadius: 10 } };
      const isHub = placed.some((hub) => hub.id === node.id);
      return isHub ? node : { ...node, style: { opacity: 0.25 } };
    });

    const styledEdges = [...membership, ...referenceEdges].map((edge) => {
      if (!hasImpact) return edge;
      if (impactPairs.has(`${edge.source}->${edge.target}`)) {
        return { ...edge, style: { ...edge.style, stroke: "#dc2626", strokeWidth: 3 }, markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#dc2626" }, animated: true };
      }
      return { ...edge, style: { ...edge.style, opacity: 0.15 } };
    });

    setNodes(styledNodes);
    setEdges(styledEdges);
    window.setTimeout(() => flowRef.current?.fitView({ padding: 0.18, duration: 400 }), 60);
  }, [network, showAll, impact]);

  if (error) return <p className="text-sm text-stone-600">{error}</p>;
  if (!network) return <p className="text-sm text-stone-600 flex items-center gap-2"><span className="spinner" /> Building the clause web</p>;

  const crossDocs = new Set(network.references.filter((ref) => ref.resolved).map((ref) => ref.target)).size;

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-4 text-sm shrink-0">
        <span className="text-stone-600">
          {network.references.length} reference{network.references.length === 1 ? "" : "s"} across {network.documents.length} documents
        </span>
        <label className="flex items-center gap-1.5 text-xs text-stone-600">
          <input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />
          Show every commercial clause
        </label>
        <span className="text-xs text-slate-500">Click a clause to edit it and see the impact.</span>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-600">
          {(Object.keys(REF_STYLE) as Reference["kind"][]).map((kind) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span style={{ width: 18, height: 0, borderTop: `2px ${REF_STYLE[kind].dash ? "dashed" : "solid"} ${REF_STYLE[kind].stroke}` }} />
              {REF_STYLE[kind].label}
            </span>
          ))}
        </div>
      </div>
      <div ref={paneRef} className="relative flex-1 min-h-0 panel overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          minZoom={0.2}
          onInit={(instance) => {
            flowRef.current = instance;
            window.setTimeout(() => instance.fitView({ padding: 0.18 }), 80);
          }}
          onNodeMouseEnter={(event, node) => {
            const source = node.data.source as Clause | Document | External | undefined;
            const role = node.data.role as Meta["role"];
            const pane = paneRef.current?.getBoundingClientRect();
            const host = (event.target as HTMLElement).closest(".react-flow__node")?.getBoundingClientRect();
            const refs = refsBySource.get(node.id) || [];
            setHover({ kind: String(node.data.kicker), role, source, refs });
            if (!pane || !host) {
              setHoverAt(null);
              return;
            }
            let x = host.right - pane.left + 10;
            let y = host.top - pane.top;
            if (x + 320 > pane.width - 8) x = host.left - pane.left - 330;
            if (x < 8) x = 8;
            if (y + 200 > pane.height - 8) y = Math.max(8, pane.height - 208);
            setHoverAt({ x, y });
          }}
          onNodeMouseLeave={() => {
            setHover(null);
            setHoverAt(null);
          }}
          onNodeClick={(_, node) => {
            const source = node.data.source as Clause | Document | External | undefined;
            if (source && "clause_id" in source) {
              setSelected(source as Clause);
              setDraft((source as Clause).text);
              setSaveError("");
            }
          }}
        >
          <Background gap={18} color="#e6e2da" />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
        {hover && hoverAt && (
          <aside className="absolute z-10 w-80 max-h-[70%] overflow-auto panel p-4 text-sm shadow-lg space-y-2 pointer-events-none" style={{ left: hoverAt.x, top: hoverAt.y }}>
            {hover.role === "hub" && hover.source && "clause_count" in hover.source ? (
              <>
                <div className="text-xs uppercase tracking-wide text-slate-500">{KIND_NAMES[(hover.source as Document).kind] || (hover.source as Document).kind} document</div>
                <div className="font-semibold">{(hover.source as Document).label}</div>
                <div className="text-xs text-slate-500">{(hover.source as Document).filename} · {(hover.source as Document).clause_count} clauses</div>
                {(hover.source as Document).title ? <p className="text-slate-600 whitespace-pre-wrap">{(hover.source as Document).title}</p> : null}
              </>
            ) : hover.role === "ext" && hover.source ? (
              <>
                <div className="text-xs uppercase tracking-wide text-slate-500">External instrument</div>
                <div className="font-semibold">{(hover.source as External).label}</div>
                <p className="text-slate-600">Cited by a clause but not uploaded to this workspace. Add it so its terms can be checked too.</p>
              </>
            ) : hover.source && "clause_id" in hover.source ? (
              <>
                <div className="text-xs uppercase tracking-wide text-slate-500">Clause §{(hover.source as Clause).section}</div>
                <div className="font-semibold">{(hover.source as Clause).heading || (hover.source as Clause).clause_id}</div>
                <p className="text-slate-600 whitespace-pre-wrap max-h-32 overflow-auto">{(hover.source as Clause).text}</p>
                {(hover.refs || []).length ? (
                  <div className="pt-1 border-t border-line">
                    <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">References</div>
                    {(hover.refs || []).map((ref) => (
                      <div key={ref.id} className="text-xs text-slate-600">
                        <span style={{ color: REF_STYLE[ref.kind].stroke }}>→</span> {ref.raw}
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}
          </aside>
        )}
        {selected && (
          <aside className="absolute right-3 top-3 z-20 w-96 max-h-[80%] overflow-auto panel p-4 text-sm shadow-lg space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Edit clause §{selected.section} · {network.documents.find((doc) => doc.index === selected.document_index)?.label || ""}
              </div>
              <button className="text-xs text-slate-500 hover:underline" onClick={() => setSelected(null)}>Close</button>
            </div>
            <textarea
              className="w-full h-40 rounded border border-line p-2 font-mono text-xs"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            {saveError && <p className="text-xs text-red-600">{saveError}</p>}
            <button className="btn" disabled={saving} onClick={applyEdit}>
              {saving ? "Recompiling…" : "Apply edit & show impact"}
            </button>
            <p className="text-xs text-slate-500">
              Recompiles the pack into a draft engine and highlights the clauses in other documents that reference this one. Approve as usual afterward.
            </p>
          </aside>
        )}
        {impact && (
          <aside className="absolute left-3 bottom-3 z-20 w-96 max-h-[70%] overflow-auto panel p-4 text-sm shadow-lg space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase tracking-wide text-slate-500">Edit impact · draft engine</div>
              <button className="text-xs text-slate-500 hover:underline" onClick={() => setImpact(null)}>Clear</button>
            </div>
            <div>
              <span className="inline-block h-2 w-2 rounded-full align-middle" style={{ background: "#2563eb" }} /> Edited{" "}
              <b>{impact.changed_clause_ids.join(", ") || "—"}</b>
            </div>
            <div>
              <span className="inline-block h-2 w-2 rounded-full align-middle" style={{ background: "#dc2626" }} />{" "}
              <span className="font-semibold text-red-600">{impact.impacted_clause_ids.length}</span> clause
              {impact.impacted_clause_ids.length === 1 ? "" : "s"} in other documents may be stranded
              {impact.impacted_clause_ids.length ? `: ${impact.impacted_clause_ids.join(", ")}` : "."}
            </div>
            <div className="pt-1 border-t border-line">
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">
                {impact.impacted_rules.length} rule{impact.impacted_rules.length === 1 ? "" : "s"} to review
              </div>
              {impact.impacted_rules.map((rule) => (
                <div key={rule.rule_id} className="text-xs text-slate-600">
                  • {rule.rule_id} <span className="text-slate-400">({rule.rule_type}, {rule.reason})</span>
                </div>
              ))}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
