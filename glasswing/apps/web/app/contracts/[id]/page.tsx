"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

type Rule = {
  rule_id: string;
  rule_type: string;
  kind: string;
  source_clause_ids: string[];
  needs_confirmation: string[];
  value_band: string;
  risk_band: string;
  warning_reasons: string[];
  human_required: boolean;
  clause_text?: string;
  obligation?: { rate?: string; application?: string | null };
  threshold?: { amount?: string };
};

type Clause = { clause_id: string; heading: string; text: string };
type Bundle = {
  bundle_id: string;
  version: number;
  status: string;
  active: boolean;
  rules: Rule[];
  clauses: Clause[];
};

export default function ContractPage() {
  const params = useParams<{ id: string }>();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [report, setReport] = useState<Array<{ title?: string; passed: boolean; author: string; expected_outcome: string; actual_outcome: string; detail: string }>>([]);
  const [message, setMessage] = useState("");
  const [switches, setSwitches] = useState<Record<string, boolean>>({});

  async function load() {
    const body = await api<{ bundle: Bundle | null }>(`/v1/contracts/${params.id}`);
    setBundle(body.bundle);
  }

  useEffect(() => {
    load().catch(() => setMessage(""));
  }, [params.id]);

  if (!bundle) return <p>{message || "Compile this contract to build the engine."}</p>;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-semibold tracking-tight">Engine version {bundle.version}</h1>
        <Link className="text-accent text-sm font-medium" href={`/work/${params.id}`}>Open workspace</Link>
      </div>
      <p className="text-sm text-stone-600">Status {bundle.status}{bundle.active ? " · live" : " · draft"}</p>
      <div className="flex gap-3">
        <button className="btn" onClick={async () => { const compiled = await api<{ bundle_id: string }>(`/v1/contracts/${params.id}/compile`, { method: "POST" }); setMessage(compiled.bundle_id); await load(); }}>Compile</button>
        <button className="btn" onClick={async () => {
          const body = await api<{ results: typeof report }>(`/v1/bundles/${bundle.bundle_id}/tests`, { method: "POST" });
          setReport(body.results);
        }}>Run unit tests</button>
        <button className="btn btn-primary" onClick={async () => {
          try {
            await api(`/v1/bundles/${bundle.bundle_id}/approve`, { method: "POST", body: JSON.stringify({ human_switches: switches }) });
            setMessage("Approved once. Live checks use this version.");
            await load();
          } catch {
            setMessage("");
          }
        }}>Approve engine once</button>
        <button className="btn" onClick={async () => {
          await api(`/v1/contracts/${params.id}/edit`, { method: "POST", body: JSON.stringify({}) });
          setMessage("Draft created. The live engine keeps running until you approve the new version.");
          await load();
        }}>Edit mid-period</button>
      </div>
      {message && <p className="text-sm">{message}</p>}
      <div className="grid gap-4">
        {bundle.rules.map((rule) => {
          const clause = bundle.clauses.find((item) => item.clause_id === rule.source_clause_ids[0]);
          const warned = rule.value_band === "high" || rule.risk_band === "high";
          return (
            <article key={rule.rule_id} className="panel p-4 grid md:grid-cols-2 gap-4">
              <div>
                <div className="text-xs uppercase tracking-wide text-stone-500">{clause?.heading || rule.source_clause_ids[0]}</div>
                <p className="mt-2 text-sm whitespace-pre-wrap">{clause?.text || rule.clause_text}</p>
              </div>
              <div className="text-sm space-y-2">
                <div className="font-medium">{rule.kind} · {rule.rule_type}</div>
                {rule.threshold && <div>Threshold {rule.threshold.amount} rate {rule.obligation?.rate} application {rule.obligation?.application || "unconfirmed"}</div>}
                {warned && <div className="text-amber-800">Warning: {rule.warning_reasons.join("; ") || `${rule.value_band} value, ${rule.risk_band} risk`}</div>}
                {rule.needs_confirmation.includes("application") && (
                  <button className="underline" onClick={async () => {
                    await api(`/v1/bundles/${bundle.bundle_id}/resolve`, { method: "POST", body: JSON.stringify({ rule_id: rule.rule_id, field: "application", value: "rate_on_each_invoice_once_crossed" }) });
                    await load();
                  }}>Confirm: rebate on each invoice after the threshold</button>
                )}
                {warned && (
                  <label className="flex gap-2 items-center">
                    <input type="checkbox" checked={switches[rule.rule_id] || false} onChange={(event) => setSwitches({ ...switches, [rule.rule_id]: event.target.checked })} />
                    Require a human for this clause only
                  </label>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {report.length > 0 && (
        <table className="w-full text-sm panel overflow-hidden">
          <thead><tr><th className="text-left p-2">Result</th><th className="text-left">Author</th><th className="text-left">Expected</th><th className="text-left">Actual</th></tr></thead>
          <tbody>
            {report.map((row, index) => (
              <tr key={index} className="border-t border-line">
                <td className="p-2">{row.passed ? "pass" : "fail"}</td>
                <td>{row.author}</td>
                <td>{row.expected_outcome}</td>
                <td>{row.actual_outcome} {row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
