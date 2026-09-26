"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

export default function FindingPage() {
  const params = useParams<{ id: string }>();
  const [finding, setFinding] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    setFinding(await api(`/v1/findings/${params.id}`));
  }
  useEffect(() => {
    load().catch(() => setMessage("Could not open this finding."));
  }, [params.id]);
  if (!finding) return <p>{message || "Loading"}</p>;
  return (
    <div className="space-y-4 max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">{money(String(finding.amount || 0))}</h1>
      <p>Status {String(finding.status)}</p>
      <p>{String(finding.explanation || "")}</p>
      <pre className="panel p-3 text-xs overflow-auto">{JSON.stringify(finding.formula_trace, null, 2)}</pre>
      <div className="flex gap-2">
        <button className="btn btn-primary" onClick={async () => { await api(`/v1/findings/${params.id}/confirm`, { method: "POST", body: JSON.stringify({ accept: true }) }); await load(); }}>Confirm</button>
        <button className="btn" onClick={async () => { await api(`/v1/findings/${params.id}/investigate`, { method: "POST" }); setMessage("Investigator returned a recommendation."); }}>Investigate</button>
        <button className="btn" onClick={async () => {
          const action = await api<{ action_id: string; draft_body?: string }>(`/v1/findings/${params.id}/actions`, { method: "POST", body: JSON.stringify({ action_type: "draft_supplier_dispute" }) });
          setMessage(action.draft_body || action.action_id);
          await api(`/v1/actions/${action.action_id}/decide`, { method: "POST", body: JSON.stringify({ accept: true }) });
        }}>Draft dispute and approve send</button>
      </div>
      {message && <p>{message}</p>}
    </div>
  );
}
