"use client";

import { useEffect, useState } from "react";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

export default function PortfolioPage() {
  const [graph, setGraph] = useState<{ nodes: Array<{ id: string; label: string; spend: string; amount_at_risk: string }>; edges: Array<{ source: string; target: string }> }>({ nodes: [], edges: [] });
  useEffect(() => {
    api<typeof graph>("/v1/portfolio/graph").then(setGraph).catch(() => undefined);
  }, []);
  const nodes = graph.nodes.map((node, index) => ({
    id: node.id,
    position: { x: (index % 4) * 220, y: Math.floor(index / 4) * 140 },
    data: { label: `${node.label} spend ${money(node.spend)} risk ${money(node.amount_at_risk)}` },
  }));
  const edges = graph.edges.map((edge, index) => ({ id: String(index), source: edge.source, target: edge.target }));
  return (
    <div className="h-[80vh] space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Suppliers</h1>
      <div className="h-[70vh] panel">
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
