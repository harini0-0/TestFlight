"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, login } from "@/lib/api";

type Pack = { pack_id: string; supplier_key: string; status: string };

const steps = [
  ["Upload documents", "Drop the commercial files in one pile. The model reads them together."],
  ["Process", "One rule engine. Tests run, then a person approves it once."],
  ["Rule engine", "A left-to-right graph. Hover a clause, or click a rule to edit it."],
  ["Live period", "Invoices are checked against the engine that is already running."],
];

export default function HomePage() {
  const router = useRouter();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [supplier, setSupplier] = useState("");
  const [busy, setBusy] = useState("");

  async function refresh() {
    if (!localStorage.getItem("glasswing_token")) await login("procurement_manager", "manager");
    const body = await api<{ packs: Pack[] }>("/v1/packs");
    setPacks(body.packs);
    setLoaded(true);
  }

  useEffect(() => {
    refresh().catch(() => setLoaded(true));
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <header className="flex items-end justify-between gap-6 shrink-0">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI procurement control</h1>
          <p className="text-sm text-stone-600 mt-1">Upload the commercial documents, process them into one rule engine, then check live transactions against that engine.</p>
        </div>
      </header>
      <section className="panel p-4 shrink-0">
        <div className="text-sm font-medium">Start a supplier workspace</div>
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy || !supplier.trim()) return;
            setBusy("Opening workspace");
            try {
              const created = await api<{ pack_id: string }>("/v1/packs", { method: "POST", body: JSON.stringify({ supplier_key: supplier }) });
              router.push(`/work/${created.pack_id}`);
            } catch {
              setBusy("");
            }
          }}
        >
          <input className="field min-w-[12rem] flex-1" placeholder="Supplier name" value={supplier} onChange={(event) => setSupplier(event.target.value)} />
          <button className="btn btn-primary" type="submit" disabled={Boolean(busy) || !supplier.trim()}>
            {busy === "Opening workspace" && <span className="spinner" />}
            Continue to upload
          </button>
          <span className="hidden h-6 w-px bg-line sm:block" aria-hidden="true" />
          <button
            className="btn"
            type="button"
            disabled={Boolean(busy)}
            onClick={async () => {
              setBusy("Loading Meridian");
              try {
                const loadedPack = await api<{ pack_id: string }>("/v1/demo/enterprise", { method: "POST" });
                router.push(`/work/${loadedPack.pack_id}`);
              } catch {
                setBusy("");
              }
            }}
          >
            {busy === "Loading Meridian" && <span className="spinner" />}
            Load Meridian Components
          </button>
          <button
            className="btn"
            type="button"
            disabled={Boolean(busy)}
            onClick={async () => {
              setBusy("Loading sample");
              try {
                const seeded = await api<{ document_id: string }>("/v1/demo/seed", { method: "POST" });
                router.push(`/work/${seeded.document_id}`);
              } catch {
                setBusy("");
              }
            }}
          >
            {busy === "Loading sample" && <span className="spinner" />}
            Load sample supplier
          </button>
        </form>
      </section>
      <ol className="grid grid-cols-2 xl:grid-cols-4 gap-3 shrink-0">
        {steps.map(([step, detail], index) => (
          <li key={step} className="panel px-3 py-3 text-sm">
            <div className="text-xs text-stone-500">Step {index + 1}</div>
            <div className="font-medium mt-1">{step}</div>
            <p className="text-stone-600 mt-1 leading-snug">{detail}</p>
          </li>
        ))}
      </ol>
      <section className="flex-1 min-h-0 flex flex-col gap-2">
        <h2 className="text-sm font-semibold shrink-0">Workspaces</h2>
        {!loaded && (
          <p className="text-sm text-stone-600 flex items-center gap-2"><span className="spinner" /> Loading workspaces</p>
        )}
        {loaded && packs.length === 0 && (
          <p className="text-sm text-stone-600">No workspaces yet. Name a supplier above, or load Meridian Components to open a finished engine.</p>
        )}
        <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 content-start overflow-auto min-h-0 flex-1 pr-1">
          {packs.map((pack) => (
            <li key={pack.pack_id} className="panel px-4 py-4 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium truncate">{pack.supplier_key}</div>
                <span className="mt-2 inline-flex rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-stone-600">{pack.status}</span>
              </div>
              <Link className="btn shrink-0" href={`/work/${pack.pack_id}`}>Open</Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
