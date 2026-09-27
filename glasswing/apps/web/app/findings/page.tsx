"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { LogoMark } from "@/components/Logo";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

type Finding = { finding_id: string; transaction_id: string; status: string; amount: string; rule_id: string };

export default function FindingsPage() {
  const [findings, setFindings] = useState<Finding[] | null>(null);
  useEffect(() => {
    api<{ findings: Finding[] }>("/v1/findings").then((body) => setFindings(body.findings)).catch(() => setFindings([]));
  }, []);
  const rows = findings || [];
  const open = rows.filter((finding) => finding.status === "open" || finding.status === "awaiting_human" || finding.status === "investigating");
  const dollars = open.reduce((sum, finding) => sum + Number(finding.amount || 0), 0);
  return (
    <div className="space-y-4 max-w-4xl">
      <header className="flex items-start gap-3.5">
        <LogoMark className="mt-0.5 h-11 w-11 shrink-0" />
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Findings</h1>
          <p className="text-sm text-slate-600 max-w-2xl">A finding is a live transaction that missed a rule. The amount is the dollars still at risk. Open means nobody has confirmed it yet. Verified means a person accepted it. Dismissed means it was set aside.</p>
        </div>
      </header>
      {findings && rows.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="panel p-4"><div className="text-xs text-slate-500">Open</div><div className="text-xl font-semibold">{open.length}</div></div>
          <div className="panel p-4"><div className="text-xs text-slate-500">Dollars still open</div><div className="text-xl font-semibold">{money(dollars)}</div></div>
          <div className="panel p-4"><div className="text-xs text-slate-500">All findings</div><div className="text-xl font-semibold">{rows.length}</div></div>
        </div>
      )}
      {findings && rows.length === 0 && (
        <div className="panel p-5 text-sm text-slate-600 space-y-2">
          <p className="font-medium text-slate-800">Nothing has leaked yet.</p>
          <p>Findings appear after a live invoice, a delivery note, or a renewal clock misses a rule. Load Meridian Components, open the live step, and play the stream. A missing rebate or a price above contract shows up here.</p>
        </div>
      )}
      {rows.length > 0 && (
        <table className="w-full panel text-sm overflow-hidden">
          <thead><tr className="text-left text-slate-500"><th className="p-3">Invoice</th><th>Status</th><th>Amount</th><th>What to do</th></tr></thead>
          <tbody>
            {rows.map((finding) => (
              <tr key={finding.finding_id} className="border-t border-line">
                <td className="p-3"><Link className="text-accent font-medium" href={`/findings/${finding.finding_id}`}>{finding.transaction_id}</Link></td>
                <td>{finding.status.replaceAll("_", " ")}</td>
                <td>{money(finding.amount)}</td>
                <td className="text-slate-600">{finding.status === "open" ? "Open the row to confirm or dismiss it." : "Already reviewed."}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
