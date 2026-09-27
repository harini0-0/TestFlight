"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { DollarSankey } from "@/components/DollarSankey";
import { LogoMark } from "@/components/Logo";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

type Roi = Record<string, string | number>;

const labels: Record<string, string> = {
  spend_monitored: "Spend checked",
  invoices_processed: "Invoices checked",
  invoices_cleared: "Invoices that passed",
  exceptions_open: "Open findings",
  amount_at_risk: "Dollars at risk",
  amount_waiting_human: "Waiting on a person",
  amount_verified: "Verified",
  amount_recovered: "Recovered",
  review_hours_avoided: "Review hours avoided",
};

const notes: Record<string, string> = {
  spend_monitored: "The sum of invoice totals posted to the live engine.",
  invoices_processed: "How many invoices have been checked.",
  invoices_cleared: "Invoices where every rule passed or did not apply.",
  exceptions_open: "Findings that are still open, waiting, or under investigation.",
  amount_at_risk: "Dollars on findings that have not been dismissed.",
  amount_waiting_human: "Dollars held because a warned clause needs a person.",
  amount_verified: "Dollars a person confirmed.",
  amount_recovered: "Confirmed dollars where the recovery action succeeded.",
  review_hours_avoided: "Cleared invoices times the minutes saved in Administration, in hours.",
};

export default function RoiPage() {
  const [roi, setRoi] = useState<Roi | null>(null);
  useEffect(() => {
    api<Roi>("/v1/roi").then(setRoi).catch(() => undefined);
  }, []);
  if (!roi) return <p className="text-sm text-slate-600">Loading value.</p>;
  const spend = Number(roi.spend_monitored || 0);
  const open = Number(roi.exceptions_open || 0);
  const risk = Number(roi.amount_at_risk || 0);
  const recovered = Number(roi.amount_recovered || 0);
  const waiting = Number(roi.amount_waiting_human || 0);
  const verified = Number(roi.amount_verified || 0);
  const clearedDollars = Math.max(spend - risk - recovered, 0);
  const bands = [
    { name: "At risk", value: risk },
    { name: "Waiting on a person", value: waiting },
    { name: "Verified", value: verified },
    { name: "Recovered", value: recovered },
  ];
  return (
    <div className="space-y-6">
      <header className="flex items-start gap-3.5">
        <LogoMark className="mt-0.5 h-11 w-11 shrink-0" />
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Value</h1>
          <p className="text-sm text-slate-600 max-w-2xl">These figures come from invoices the live engine has already checked. Spend is the invoice total. At risk is money on findings that are still open. Recovered is money after a confirmed recovery action.</p>
        </div>
      </header>
      {Number(roi.invoices_processed || 0) === 0 && (
        <div className="panel p-5 text-sm text-slate-600">
          <p className="font-medium text-slate-800">No invoices have been checked yet.</p>
          <p className="mt-2">Play the Meridian live stream, or post an invoice from a workspace. Spend, cleared invoices, and dollars at risk fill in after that.</p>
        </div>
      )}
      <div className="grid md:grid-cols-3 gap-4">
        {Object.entries(roi).map(([key, value]) => (
          <div key={key} className="panel p-4">
            <div className="text-xs uppercase text-slate-500">{labels[key] || key.replaceAll("_", " ")}</div>
            <div className="text-xl font-semibold mt-1">{String(key).includes("amount") || key.includes("spend") ? money(String(value)) : String(value)}</div>
            <p className="text-xs text-slate-600 mt-2">{notes[key]}</p>
          </div>
        ))}
      </div>
      <div className="h-64 panel p-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bands}>
            <XAxis dataKey="name" />
            <YAxis />
            <Bar dataKey="value" fill="#142033" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="panel p-4">
        <DollarSankey monitored={spend} cleared={clearedDollars} atRisk={risk} recovered={recovered} />
      </div>
      <p className="text-sm text-stone-600">Open exceptions: {open}. Band width is dollars from monitored spend into cleared, at risk, and recovered.</p>
    </div>
  );
}
