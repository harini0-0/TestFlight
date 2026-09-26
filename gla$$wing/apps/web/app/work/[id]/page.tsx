"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { RuleGraph } from "@/components/RuleGraph";
import { API_URL, api, fail, token } from "@/lib/api";

type Rule = {
  rule_id: string;
  rule_type: string;
  needs_confirmation: string[];
  source_clause_ids: string[];
  obligation?: { application?: string | null; rate?: string };
  threshold?: { amount?: string };
};
type Pack = {
  pack_id: string;
  supplier_key: string;
  status: string;
  files: Array<{ document_id: string; kind: string; filename: string }>;
  bundle: { bundle_id: string; version: number; status: string; active: boolean; rules: Rule[] } | null;
};

const steps = [
  ["upload", "1. Upload documents"],
  ["process", "2. Process"],
  ["engine", "3. Rule engine"],
  ["live", "4. Live period"],
] as const;

const zones = [
  ["contract", "Contracts"],
  ["rebate", "Rebates"],
  ["discount", "Discounts"],
  ["sla", "SLAs"],
  ["renewal", "Renewal dates"],
  ["payment_terms", "Payment terms"],
] as const;

type Step = (typeof steps)[number][0];

export default function WorkPage() {
  const params = useParams<{ id: string }>();
  const [pack, setPack] = useState<Pack | null>(null);
  const [step, setStep] = useState<Step>("upload");
  const [ready, setReady] = useState(false);
  const [live, setLive] = useState(false);
  const [message, setMessage] = useState("");
  const [report, setReport] = useState<Array<{ passed: boolean; author: string; expected_outcome: string; actual_outcome: string; detail?: string }>>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [invoice, setInvoice] = useState({ number: "", date: "2026-03-01", amount: "1000", description: "Goods" });
  const [stream, setStream] = useState<Array<{ filename: string; summary: string }>>([]);
  const [playing, setPlaying] = useState(false);

  async function load() {
    const body = await api<Pack>(`/v1/packs/${params.id}`);
    setPack(body);
    return body;
  }

  useEffect(() => {
    load()
      .then(async (body) => {
        let running = Boolean(body.bundle?.active);
        if (!running && body.bundle) {
          const map = await api<{ active?: boolean }>(`/v1/contracts/${params.id}/control-map`).catch(() => null);
          running = Boolean(map?.active);
        }
        setLive(running);
        if (running) setStep("engine");
        else if (body.bundle) setStep("process");
        setReady(true);
      })
      .catch(() => setMessage("Could not open this workspace"));
  }, [params.id]);

  useEffect(() => {
    if (pack?.supplier_key !== "meridian-components") return;
    api<{ files: Array<{ filename: string; summary: string }> }>("/v1/demo/enterprise/live")
      .then((body) => setStream(body.files))
      .catch(() => undefined);
  }, [pack?.supplier_key]);

  async function playStream() {
    setPlaying(true);
    try {
      for (;;) {
        const step = await api<{
          done: boolean;
          filename: string;
          summary: string;
          transaction_id: string;
          violations: Array<{ explanation: string; amount: string | null }>;
        }>(`/v1/packs/${params.id}/live-next`, { method: "POST" });
        if (step.done) {
          setMessage("The live stream has finished. Every sample transaction has been checked.");
          break;
        }
        const leaks = step.violations || [];
        setMessage(
          leaks.length
            ? `${step.filename}: ${leaks.length} leak${leaks.length === 1 ? "" : "s"} on ${step.transaction_id}. ${leaks.map((leak) => leak.explanation).join(" ")}`
            : `${step.filename}: ${step.transaction_id} passed. ${step.summary}`,
        );
        setRefreshKey((value) => value + 1);
        await new Promise((resolve) => setTimeout(resolve, 1100));
      }
    } catch {
      setMessage("The live stream stopped.");
    } finally {
      setPlaying(false);
    }
  }

  async function upload(kind: string, files: FileList | File[]) {
    for (const file of Array.from(files)) {
      const response = await fetch(`${API_URL}/v1/packs/${params.id}/files`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token()}`,
          "X-Document-Kind": kind,
          "X-Filename": file.name,
          "Content-Type": file.type || "text/plain",
        },
        body: await file.arrayBuffer(),
      });
      if (!response.ok) fail(await response.text(), "Upload failed");
    }
    await load();
  }

  if (!pack) return <p className="text-sm text-slate-600">{message || "Opening workspace."}</p>;

  const rules = pack.bundle?.rules || [];

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-6">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Supplier workspace</div>
          <h1 className="text-2xl font-semibold tracking-tight mt-1">{pack.supplier_key}</h1>
        </div>
          <div className="text-sm text-slate-500">{live ? "Live engine running" : pack.bundle ? `Engine v${pack.bundle.version} · ${pack.bundle.status}` : "Not processed"}{live && pack.bundle && !pack.bundle.active ? ` · draft v${pack.bundle.version} waiting` : ""}</div>
      </header>
      <div className="grid grid-cols-4 gap-2">
        {steps.map(([id, label]) => (
          <button key={id} className={step === id ? "btn btn-primary" : "btn"} onClick={() => setStep(id)}>{label}</button>
        ))}
      </div>
      {message && <p className="text-sm text-slate-700">{message}</p>}

      {step === "upload" && (
        <section className="space-y-4">
          <p className="text-sm text-slate-600">Add every commercial file for this supplier. You can drop more than one file in each group.</p>
          <div className="grid md:grid-cols-3 gap-3">
            {zones.map(([kind, label]) => (
              <label key={kind} className="panel p-4 block cursor-pointer" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); upload(kind, event.dataTransfer.files).catch(() => undefined); }}>
                <div className="font-medium">{label}</div>
                <div className="text-xs text-slate-500 mt-1">TXT, CSV, or PDF</div>
                <input className="mt-3 block w-full text-sm" type="file" accept=".txt,.csv,.pdf,text/plain,application/pdf" multiple onChange={(event) => { if (event.target.files) upload(kind, event.target.files).catch(() => undefined); }} />
                <ul className="mt-3 text-xs text-slate-600 space-y-1">
                  {pack.files.filter((file) => file.kind === kind).map((file) => <li key={file.document_id}>{file.filename}</li>)}
                </ul>
              </label>
            ))}
          </div>
          <button className="btn btn-primary" disabled={!ready} onClick={() => setStep("process")}>Continue to process</button>
        </section>
      )}

      {step === "process" && (
        <section className="space-y-4 max-w-3xl">
          <p className="text-sm text-slate-600">{pack.files.length} file{pack.files.length === 1 ? "" : "s"} ready. Processing compiles one rule engine and runs its tests. Approval is the single human gate.</p>
          <div className="flex gap-3">
            <button className="btn btn-primary" onClick={async () => {
              const processed = await api<{ tests: { results: typeof report }; bundle_id: string }>(`/v1/packs/${params.id}/process`, { method: "POST" });
              setReport(processed.tests.results || []);
              setMessage("Processing finished. Review the tests, then approve the engine.");
              await load();
            }}>Process documents</button>
            <button className="btn" disabled={!pack.bundle} onClick={async () => {
              if (!pack.bundle) return;
              try {
                await api(`/v1/bundles/${pack.bundle.bundle_id}/approve`, { method: "POST", body: JSON.stringify({ human_switches: {} }) });
                setMessage("Engine approved. Live transactions now use this version.");
                await load();
                setStep("engine");
              } catch {
                setMessage("");
              }
            }}>Approve engine</button>
          </div>
          {rules.some((rule) => rule.needs_confirmation.includes("application")) && (
            <div className="panel p-4 space-y-2">
              <div className="font-medium">Confirm rebate application</div>
              {rules.filter((rule) => rule.needs_confirmation.includes("application")).map((rule) => (
                <button key={rule.rule_id} className="btn" onClick={async () => {
                  await api(`/v1/bundles/${pack.bundle?.bundle_id}/resolve`, { method: "POST", body: JSON.stringify({ rule_id: rule.rule_id, field: "application", value: "rate_on_each_invoice_once_crossed" }) });
                  setMessage("Application confirmed. Process the tests again, then approve.");
                  await load();
                }}>Use the rate on each invoice after the threshold · clause {rule.source_clause_ids[0]}</button>
              ))}
            </div>
          )}
          {report.length > 0 && (
            <table className="w-full text-sm panel overflow-hidden">
              <thead><tr className="text-left text-slate-500"><th className="p-3">Result</th><th>Author</th><th>Expected</th><th>Actual</th></tr></thead>
              <tbody>
                {report.map((row, index) => (
                  <tr key={index} className="border-t border-line">
                    <td className="p-3">{row.passed ? "Pass" : "Fail"}</td>
                    <td>{row.author}</td>
                    <td>{row.expected_outcome}</td>
                    <td>{row.actual_outcome} {row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {step === "engine" && (
        <section className="space-y-3">
          <p className="text-sm text-slate-600">Hover a node for the clause, formula, and ledger. Click a rule to edit it. A live edit becomes the next draft and does not replace the running engine until you approve it.</p>
          <RuleGraph documentId={params.id} refreshKey={refreshKey} />
        </section>
      )}

      {step === "live" && (
        <section className="space-y-4">
          <div className="panel p-4 space-y-3">
            <h2 className="font-semibold">What this stream does</h2>
            <p className="text-sm text-slate-600">Each file is posted in order against the engine that is already live. A dashed line then runs from the agreement through the clause and the rule to the result. A leak pulses red on the rule and on the finding. A pass stays still.</p>
            {pack.supplier_key === "meridian-components" ? (
              <>
                <ol className="space-y-2 text-sm">
                  {stream.map((file) => (
                    <li key={file.filename}>
                      <div className="font-medium">{file.filename}</div>
                      <div className="text-slate-600">{file.summary}</div>
                    </li>
                  ))}
                </ol>
                <button className="btn btn-primary" disabled={playing || !live} onClick={() => playStream()}>
                  {playing ? "Playing…" : "Play live stream"}
                </button>
              </>
            ) : (
              <p className="text-sm text-slate-600">This workspace uses the forms below. Load Meridian Components from the home page to play the prepared invoice stream.</p>
            )}
          </div>
          <div className="grid lg:grid-cols-2 gap-4">
            <form className="panel p-4 space-y-3" onSubmit={async (event) => {
              event.preventDefault();
              const id = `INV-${invoice.number || crypto.randomUUID().slice(0, 8)}`;
              await api("/v1/transactions", {
                method: "POST",
                headers: { "Idempotency-Key": id },
                body: JSON.stringify({
                  transaction_id: id,
                  supplier_key: pack.supplier_key,
                  invoice_number: invoice.number || id,
                  invoice_date: invoice.date,
                  currency: "USD",
                  lines: [{
                    description: invoice.description,
                    category: "goods",
                    quantity: "1",
                    unit_price: { amount: invoice.amount, currency: "USD" },
                    extended_amount: { amount: invoice.amount, currency: "USD" },
                  }],
                }),
              });
              setMessage(`Invoice ${id} checked against the live engine.`);
              setRefreshKey((value) => value + 1);
            }}>
              <h2 className="font-semibold">Upload a live invoice</h2>
              <input className="field" placeholder="Invoice number" value={invoice.number} onChange={(event) => setInvoice({ ...invoice, number: event.target.value })} />
              <input className="field" type="date" value={invoice.date} onChange={(event) => setInvoice({ ...invoice, date: event.target.value })} />
              <input className="field" placeholder="Amount" value={invoice.amount} onChange={(event) => setInvoice({ ...invoice, amount: event.target.value })} />
              <input className="field" placeholder="Description" value={invoice.description} onChange={(event) => setInvoice({ ...invoice, description: event.target.value })} />
              <button className="btn btn-primary" type="submit">Check invoice</button>
            </form>
            <div className="panel p-4 space-y-3">
              <h2 className="font-semibold">Upload a CSV of invoices</h2>
              <textarea id="csv" className="field h-28" defaultValue={"supplier_key,invoice_number,invoice_date,quantity,unit_price,description,category\n"} />
              <button className="btn" onClick={async () => {
                const raw = (document.getElementById("csv") as HTMLTextAreaElement).value.trim();
                const lines = raw.split(/\r?\n/).filter((line) => line.trim());
                const header = lines[0]?.split(",").map((cell) => cell.trim()) || [];
                const supplierColumn = header.indexOf("supplier_key");
                let rewritten = false;
                const body = lines.map((line, index) => {
                  if (index === 0 || supplierColumn < 0) return line;
                  const cells = line.split(",");
                  if ((cells[supplierColumn] || "").trim() !== pack.supplier_key) rewritten = true;
                  cells[supplierColumn] = pack.supplier_key;
                  return cells.join(",");
                }).join("\n");
                try {
                  const posted = await api<{ results: Array<{ transaction_id: string; evaluations: Array<{ outcome: string; explanation: string }> }> }>("/v1/connectors/csv", { method: "POST", body: JSON.stringify({ csv: body }) });
                  const leaks = posted.results.flatMap((row) => row.evaluations.filter((item) => item.outcome === "violation").map((item) => `${row.transaction_id}: ${item.explanation}`));
                  setMessage(
                    rewritten
                      ? `Checked against ${pack.supplier_key}, not the supplier name in the file. ${leaks.length ? leaks.join(" ") : "No leaks."}`
                      : leaks.length ? leaks.join(" ") : "CSV invoices checked. No leaks.",
                  );
                  setRefreshKey((value) => value + 1);
                } catch {
                  setMessage("");
                }
              }}>Upload CSV</button>
              <h2 className="font-semibold pt-2">Add a document during the period</h2>
              <input type="file" accept=".txt,.csv,.pdf,text/plain,application/pdf" onChange={(event) => { if (event.target.files) upload("contract", event.target.files).then(() => setMessage("Document stored. Rebuild the draft when you want it in the engine.")).catch(() => undefined); }} />
              <button className="btn" onClick={async () => {
                await api(`/v1/packs/${params.id}/process`, { method: "POST" });
                setMessage("A new draft was compiled. The live engine keeps running until you approve the draft.");
                await load();
              }}>Rebuild draft from documents</button>
            </div>
          </div>
          <RuleGraph documentId={params.id} refreshKey={refreshKey} live />
        </section>
      )}
    </div>
  );
}
