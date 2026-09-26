"use client";

import { Sankey } from "@visx/sankey";

type FlowNode = { name: string; amount: number };
type FlowLink = { source: number; target: number; value: number; color: string };

const COLORS = ["#142033", "#047857", "#b45309", "#0369a1"];

function dollars(amount: number): string {
  return amount.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function num(value: number | undefined, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function DollarSankey({
  monitored,
  cleared,
  atRisk,
  recovered,
}: {
  monitored: number;
  cleared: number;
  atRisk: number;
  recovered: number;
}) {
  const parts = [
    { name: "Cleared", amount: cleared, color: COLORS[1] },
    { name: "At risk", amount: atRisk, color: COLORS[2] },
    { name: "Recovered", amount: recovered, color: COLORS[3] },
  ].filter((part) => part.amount > 0);
  const largest = Math.max(monitored, ...parts.map((part) => part.amount), 1);
  const root = {
    nodes: [{ name: "Monitored", amount: monitored }, ...parts.map(({ name, amount }) => ({ name, amount }))],
    links: parts.map((part, index) => ({
      source: 0,
      target: index + 1,
      value: Math.max(part.amount, largest * 0.12),
      color: part.color,
    })),
  };

  if (parts.length === 0) {
    return (
      <svg width="100%" viewBox="0 0 920 300" role="img" aria-label="No dollar flow to display yet">
        <text x={460} y={150} textAnchor="middle" fontSize={14} fill="#64748b">
          No dollars to flow yet.
        </text>
      </svg>
    );
  }

  return (
    <svg width="100%" viewBox="0 0 920 300" role="img" aria-label="Dollar flow from monitored spend into cleared, at risk, and recovered">
      <Sankey<FlowNode, FlowLink> root={root} nodeWidth={18} nodePadding={36} size={[520, 260]}>
        {({ graph, createPath }) => (
          <g transform="translate(190, 16)">
            {graph.links.map((link, index) => (
              <path
                key={index}
                d={createPath(link) ?? ""}
                fill="none"
                stroke={link.color}
                strokeOpacity={0.55}
                strokeWidth={Math.max(num(link.width, 1), 8)}
              />
            ))}
            {graph.nodes.map((node, index) => {
              const x0 = num(node.x0);
              const x1 = num(node.x1);
              const y0 = num(node.y0);
              const y1 = num(node.y1);
              const onLeft = index === 0;
              return (
                <g key={node.name}>
                  <rect x={x0} y={y0} width={Math.max(x1 - x0, 1)} height={Math.max(y1 - y0, 1)} fill={COLORS[index]} />
                  <text
                    x={onLeft ? x0 - 12 : x1 + 12}
                    y={(y0 + y1) / 2}
                    dy="0.35em"
                    textAnchor={onLeft ? "end" : "start"}
                    fontSize={14}
                    fill="#142033"
                  >
                    {node.name} {dollars(node.amount)}
                  </text>
                </g>
              );
            })}
          </g>
        )}
      </Sankey>
    </svg>
  );
}
