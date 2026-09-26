"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, login } from "@/lib/api";

type Pack = { pack_id: string; supplier_key: string; status: string };

const steps = [
  ["Upload documents", "Contracts, rebates, discounts, service levels, renewal dates, and payment terms go in as separate files."],
  ["Process", "The files become one rule engine. Tests run, then a person approves it once."],
  ["Rule engine", "The approved engine is a graph. Hover a node for the clause, and click a rule to edit it."],
  ["Live period", "Invoices, a delivery note, and the renewal clock are checked against the engine that is already running."],
];

export default function HomePage() {
  const router = useRouter();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [supplier, setSupplier] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    if (!localStorage.getItem("glasswing_token")) await login("procurement_manager", "manager");
    const body = await api<{ packs: Pack[] }>("/v1/packs");
    setPacks(body.packs);
  }

  useEffect(() => {
    refresh().catch(() => setError(""));
  }, []);

  return (
    <div className="space-y-8 max-w-5xl">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">AI procurement control</h1>
        <p className="text-slate-600 max-w-2xl">Upload the commercial documents, process them into one rule engine, then check live transactions against that engine.</p>
        <ol className="grid md:grid-cols-4 gap-3">
          {steps.map(([step, detail], index) => (
            <li key={step} className="panel px-3 py-3 text-sm">
              <div className="text-xs text-slate-500">Step {index + 1}</div>
              <div className="font-medium mt-1">{step}</div>
              <p className="text-slate-600 mt-2">{detail}</p>
            </li>
          ))}
        </ol>
      </header>
      <section className="panel p-5 space-y-4">
        <h2 className="text-lg font-semibold">Start a supplier workspace</h2>
        <div className="flex gap-3">
          <input className="field max-w-sm" placeholder="Supplier name" value={supplier} onChange={(event) => setSupplier(event.target.value)} />
          <button
            className="btn btn-primary"
            onClick={async () => {
              const created = await api<{ pack_id: string }>("/v1/packs", { method: "POST", body: JSON.stringify({ supplier_key: supplier }) });
              router.push(`/work/${created.pack_id}`);
            }}
          >
            Continue to upload
          </button>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            className="btn btn-primary"
            onClick={async () => {
              const loaded = await api<{ pack_id: string }>("/v1/demo/enterprise", { method: "POST" });
              router.push(`/work/${loaded.pack_id}`);
            }}
          >
            Load Meridian Components
          </button>
          <button
            className="btn"
            onClick={async () => {
              const seeded = await api<{ document_id: string }>("/v1/demo/seed", { method: "POST" });
              router.push(`/work/${seeded.document_id}`);
            }}
          >
            Load sample supplier
          </button>
        </div>
        <p className="text-sm text-slate-600">Meridian Components is a full supplier pack: a master agreement, a price schedule, rebates, volume discounts, service levels, renewal dates, and payment terms. The live invoices stay unposted until you play them.</p>
        {error && <p className="text-sm text-red-700">{error}</p>}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Workspaces</h2>
        {packs.length === 0 && <p className="text-sm text-slate-600">No workspaces yet. Name a supplier above, or load Meridian Components to open a finished engine.</p>}
        <ul className="space-y-2">
          {packs.map((pack) => (
            <li key={pack.pack_id} className="panel px-4 py-3 flex justify-between items-center">
              <div>
                <div className="font-medium">{pack.supplier_key}</div>
                <div className="text-sm text-slate-500">{pack.status}</div>
              </div>
              <Link className="text-sm text-accent font-medium" href={`/work/${pack.pack_id}`}>Open</Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
