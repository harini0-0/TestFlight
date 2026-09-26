"use client";

import { RuleGraph } from "@/components/RuleGraph";
import { useParams } from "next/navigation";

export default function MapPage() {
  const params = useParams<{ id: string }>();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Rule engine</h1>
      <RuleGraph documentId={params.id} />
    </div>
  );
}
