"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { RuleGraph } from "@/components/RuleGraph";
import { API_URL, api, fail, streamNdjson, token, type ProgressEvent } from "@/lib/api";

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

type Step = (typeof steps)[number][0];

function processTone(kind: "current" | "done" | "waiting") {
  if (kind === "current") return "panel p-3 space-y-2 ring-2 ring-accent min-w-0";
  return "panel p-3 space-y-2 min-w-0";
}

function processingCopy(busy: string, progress: ProgressEvent | null): { title: string; detail: string } | null {
  if (busy === "Compiling the engine") {
    return {
      title: progress && progress.total > 0 ? `Reading part ${Math.max(progress.index, 1)} of ${progress.total}` : "AI is reading the documents",
      detail: progress?.detail || "Long documents are split into parts so every clause is read. Nothing is skipped to fit one request.",
    };
  }
  if (busy === "Running practice checks") {
    return { title: "Running the practice checks", detail: "Each rule is being tested before you review the engine." };
  }
  if (busy === "Confirming rebate") {
    return { title: "Saving the rebate confirmation", detail: "The engine will use this application on the next practice run." };
  }
  if (busy === "Checking the invoice") {
    return {
      title: progress && progress.total > 0 ? `Invoice part ${Math.max(progress.index, 1)} of ${progress.total}` : "AI is reading this invoice",
      detail: progress?.detail || "The invoice is read in parts, then each line is checked against the rules.",
    };
  }
  return null;
}

export default function WorkPage() {
  const params = useParams<{ id: string }>();
  const [pack, setPack] = useState<Pack | null>(null);
  const [step, setStep] = useState<Step>("upload");
  const [ready, setReady] = useState(false);
  const [live, setLive] = useState(false);
  const [message, setMessage] = useState("");
  const [report, setReport] = useState<Array<{ passed: boolean; author: string; expected_outcome: string; actual_outcome: string; detail?: string }>>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [invoiceText, setInvoiceText] = useState("");
  const [invoiceFile, setInvoiceFile] = useState<File | null>(null);
  const [stream, setStream] = useState<Array<{ filename: string; summary: string }>>([]);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState("");
  const [awaitingRetest, setAwaitingRetest] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showPeriod, setShowPeriod] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [acks, setAcks] = useState([false, false, false]);
  const [showFlow, setShowFlow] = useState(false);
  const [spotlight, setSpotlight] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [aiProgress, setAiProgress] = useState<ProgressEvent | null>(null);

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
    setShowFlow(true);
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

  async function upload(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return false;
    setUploading(true);
    let stored = false;
    try {
      for (const file of list) {
        const response = await fetch(`${API_URL}/v1/packs/${params.id}/files`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token()}`,
            "X-Document-Kind": "document",
            "X-Filename": file.name,
            "Content-Type": file.type || "text/plain",
          },
          body: await file.arrayBuffer(),
        });
        if (!response.ok) fail(await response.text(), "Upload failed");
      }
      stored = true;
    } catch {
      setMessage("");
    } finally {
      setUploading(false);
      await load().catch(() => undefined);
    }
    return stored;
  }

  async function checkInvoice() {
    if (!pack) return;
    const supplierKey = pack.supplier_key;
    const file = invoiceFile;
    const text = invoiceText.trim();
    if (!file && !text) return;
    setBusy("Checking the invoice");
    setAiProgress(null);
    try {
      let posted: { accepted: number; results: Array<{ transaction_id: string; evaluations: Array<{ outcome: string; explanation: string }> }> };
      if (file) {
        posted = await streamNdjson(`/v1/transactions/interpret`, {
          method: "POST",
          headers: {
            "X-Filename": file.name,
            "X-Supplier-Key": supplierKey,
            "Content-Type": file.type || "application/octet-stream",
          },
          body: await file.arrayBuffer(),
        }, setAiProgress);
      } else {
        posted = await streamNdjson("/v1/transactions/interpret", {
          method: "POST",
          body: JSON.stringify({ text, supplier_key: supplierKey }),
        }, setAiProgress);
      }
      const leaks = posted.results.flatMap((row) =>
        row.evaluations.filter((item) => item.outcome === "violation").map((item) => `${row.transaction_id}: ${item.explanation}`),
      );
      setMessage(
        leaks.length
          ? leaks.join(" ")
          : `Checked ${posted.accepted} transaction${posted.accepted === 1 ? "" : "s"}. No leaks.`,
      );
      setInvoiceFile(null);
      setSpotlight(
        posted.results
          .filter((row) => row.evaluations.some((item) => item.outcome === "violation"))
          .map((row) => row.transaction_id),
      );
      setShowFlow(true);
      setRefreshKey((value) => value + 1);
    } catch {
      setMessage("");
    } finally {
      setBusy("");
      setAiProgress(null);
    }
  }

  if (!pack) {
    return (
      <p className="text-sm text-stone-600 flex items-center gap-2">
        <span className="spinner" />
        {message || "Opening workspace"}
      </p>
    );
  }

  const rules = pack.bundle?.rules || [];
  const openRebates = rules.filter((rule) => rule.needs_confirmation.includes("application"));
  const confirmedRebates = rules.filter((rule) => Boolean(rule.obligation?.application) && !rule.needs_confirmation.includes("application"));
  const retestOnly = Boolean(pack.bundle) && openRebates.length === 0 && awaitingRetest;
  const processStage: 1 | 2 | 3 = !pack.bundle ? 1 : openRebates.length ? 2 : awaitingRetest ? 1 : 3;
  const stageTone = (panel: 1 | 2 | 3): "current" | "done" | "waiting" => {
    if (panel === processStage) return "current";
    if (panel === 1 && pack.bundle) return "done";
    if (panel === 2 && pack.bundle && openRebates.length === 0) return "done";
    return "waiting";
  };

  const processing = (step === "process" || step === "live") ? processingCopy(busy, aiProgress) : null;
  const meter = aiProgress && aiProgress.total > 0 ? Math.min(100, Math.round((aiProgress.index / aiProgress.total) * 100)) : 8;

  return (
    <>
    <div className="flex h-full min-h-0 flex-col gap-3" inert={processing ? true : undefined}>
      <header className="flex items-end justify-between gap-6 shrink-0">
        <div>
          <div className="text-xs uppercase tracking-wide text-stone-500">Supplier workspace</div>
          <h1 className="text-2xl font-semibold tracking-tight mt-1">{pack.supplier_key}</h1>
        </div>
        <div className="text-sm text-stone-500">{live ? "Live engine running" : pack.bundle ? `Engine v${pack.bundle.version} · ${pack.bundle.status}` : "Not processed"}{live && pack.bundle && !pack.bundle.active ? ` · draft v${pack.bundle.version} waiting` : ""}</div>
      </header>
      <div className="grid grid-cols-4 gap-2 shrink-0">
        {steps.map(([id, label]) => (
          <button key={id} className={step === id ? "btn btn-primary" : "btn"} onClick={() => setStep(id)}>{label}</button>
        ))}
      </div>
      {message && <p className="text-sm text-stone-700 shrink-0">{message}</p>}

      {step === "upload" && (
        <section key="upload" className="step-pane flex-1 min-h-0 flex flex-col gap-3">
          <label
            className={`dropzone shrink-0 ${dragOver ? "is-over" : ""}`}
            onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => { event.preventDefault(); setDragOver(false); upload(event.dataTransfer.files); }}
          >
            <div className="min-w-0">
              <div className="text-sm font-medium">{uploading ? "Adding the files" : "Drop documents here"}</div>
              <p className="text-xs text-stone-600 mt-0.5">TXT, CSV, PDF, or Excel (.xlsx). Several files at once is fine. No category needed.</p>
            </div>
            <input
              className="block text-sm shrink-0"
              type="file"
              accept=".txt,.csv,.pdf,.xlsx,.xlsm,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              multiple
              disabled={uploading}
              onChange={(event) => {
                if (event.target.files) upload(event.target.files);
                event.target.value = "";
              }}
            />
            {uploading && <span className="spinner shrink-0" />}
          </label>
          <div className="panel flex-1 min-h-0 flex flex-col overflow-hidden">
            <div className="px-4 py-3 border-b border-line text-sm font-medium shrink-0">
              {pack.files.length === 0 ? "No documents yet" : `${pack.files.length} document${pack.files.length === 1 ? "" : "s"}`}
            </div>
            {pack.files.length === 0 ? (
              <p className="px-4 py-3 text-sm text-stone-600">Add contracts, rebates, discounts, service levels, and payment terms. Processing reads each file as text.</p>
            ) : (
              <ul className="min-h-0 flex-1 overflow-auto">
                {pack.files.map((file) => (
                  <li key={file.document_id} className="px-4 py-2.5 border-b border-line last:border-b-0 text-sm truncate">{file.filename}</li>
                ))}
              </ul>
            )}
          </div>
          <button className="btn btn-primary shrink-0 self-start" disabled={!ready || uploading} onClick={() => setStep("process")}>Continue to process</button>
        </section>
      )}

      {step === "process" && (
        <section key="process" className="step-pane flex-1 min-h-0 flex flex-col gap-3">
          <p className="text-sm text-stone-600 shrink-0">This step turns the {pack.files.length} uploaded file{pack.files.length === 1 ? "" : "s"} into one rule engine, checks it with practice cases, and asks you to approve it once. Live invoices are not checked until you approve.</p>
          <div className="grid grid-cols-3 gap-3 shrink-0">
            <div className={processTone(stageTone(1))}>
              <div className="text-sm font-semibold text-ink">1 · Compile and test {processStage > 1 ? "· Done" : ""}</div>
              <p className="text-sm text-stone-700">{retestOnly ? "The rebate confirmations are saved. Run the practice checks on this engine. This does not read the documents again." : pack.bundle ? "Already compiled. Process the documents again only if the uploaded files changed." : "An AI reads the uploaded files, writes one rule engine, and runs the practice checks. Nothing is live yet."}</p>
              <button className={processStage === 1 ? "btn btn-primary" : "btn"} disabled={Boolean(busy)} onClick={async () => {
                if (retestOnly && pack.bundle) {
                  setBusy("Running practice checks");
                  try {
                    const tested = await api<{ results: typeof report }>(`/v1/bundles/${pack.bundle.bundle_id}/tests`, { method: "POST" });
                    setReport(tested.results || []);
                    setAwaitingRetest(false);
                    setMessage("Practice checks finished. Review the engine.");
                    await load();
                  } catch {
                    setMessage("");
                  } finally {
                    setBusy("");
                  }
                  return;
                }
                setBusy("Compiling the engine");
                setAiProgress(null);
                try {
                  const processed = await streamNdjson<{ tests: { results: typeof report }; rules: Rule[]; bundle_id: string }>(`/v1/packs/${params.id}/process`, { method: "POST" }, setAiProgress);
                  setReport(processed.tests?.results || []);
                  setAwaitingRetest(false);
                  const body = await load();
                  const rebatesOpen = (body.bundle?.rules || processed.rules || []).some((rule) => rule.needs_confirmation.includes("application"));
                  if (rebatesOpen) {
                    setMessage("Processing finished. Confirm how each rebate applies, then view the engine.");
                    setStep("process");
                  } else {
                    setMessage("Processing finished. The rule engine is ready to review.");
                    setStep("engine");
                  }
                } catch (error) {
                  setMessage(error instanceof Error ? error.message : "Processing failed");
                } finally {
                  setBusy("");
                  setAiProgress(null);
                }
              }}>{busy === "Compiling the engine" ? "Compiling the engine" : busy === "Running practice checks" ? "Running practice checks" : retestOnly ? "Run practice checks" : "Process documents"}</button>
            </div>
            <div className={processTone(stageTone(2))}>
              <div className="text-sm font-semibold text-ink">2 · Confirm how each rebate applies</div>
              {openRebates.length > 0 || confirmedRebates.length > 0 ? (
                <>
                  <p className="text-sm text-stone-700">The clause names a rate and a spend line, but not whether that rate is taken on each invoice after the line is crossed. Tick each box to confirm that. Then run the practice checks again.</p>
                  {openRebates.map((rule) => (
                    <label key={rule.rule_id} className="flex items-start gap-2 text-sm font-medium text-ink">
                      <input
                        type="checkbox"
                        className="mt-1"
                        disabled={Boolean(busy)}
                        onChange={async (event) => {
                          if (!event.target.checked) return;
                          setBusy("Confirming rebate");
                          try {
                            await api(`/v1/bundles/${pack.bundle?.bundle_id}/resolve`, { method: "POST", body: JSON.stringify({ rule_id: rule.rule_id, field: "application", value: "rate_on_each_invoice_once_crossed" }) });
                            setAwaitingRetest(true);
                            setMessage("Application confirmed. Process the tests again, then view the engine.");
                            await load();
                          } catch {
                            event.target.checked = false;
                            setMessage("");
                          } finally {
                            setBusy("");
                          }
                        }}
                      />
                      <span>Use the rate on each invoice after the threshold · clause {rule.source_clause_ids[0]}</span>
                    </label>
                  ))}
                  {confirmedRebates.map((rule) => (
                    <label key={rule.rule_id} className="flex items-start gap-2 text-sm font-medium text-ink">
                      <input type="checkbox" className="mt-1" checked disabled />
                      <span>Use the rate on each invoice after the threshold · clause {rule.source_clause_ids[0]}</span>
                    </label>
                  ))}
                </>
              ) : (
                <p className="text-sm text-stone-700">Not needed. No clause leaves the rebate application open.</p>
              )}
            </div>
            <div className={processTone(stageTone(3))}>
              <div className="text-sm font-semibold text-ink">3 · Review the engine {live && pack.bundle?.active ? "· Live" : ""}</div>
              <p className="text-sm text-stone-700">Open the graph and check that each clause, rule, and finding is in place. Approval happens there, after you confirm you have read the rules.</p>
              {!pack.bundle && <p className="text-sm text-ink">Process the documents first.</p>}
              {openRebates.length > 0 && <p className="text-sm text-ink">Tick the open rebate boxes first.</p>}
              {awaitingRetest && <p className="text-sm text-ink">Run the practice checks again, then view the engine.</p>}
              <button className={processStage === 3 ? "btn btn-primary" : "btn"} disabled={!pack.bundle || openRebates.length > 0 || awaitingRetest || Boolean(busy)} onClick={() => setStep("engine")}>View engine</button>
            </div>
          </div>
          {report.length > 0 && (
            <div className="flex-1 min-h-0 overflow-auto panel">
              <p className="px-3 pt-3 text-xs text-stone-500">Result is pass or fail. Author is who wrote the check. Expected is the required outcome. Actual is what the engine did. A fail blocks approval.</p>
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white"><tr className="text-left text-stone-500"><th className="p-3">Result</th><th>Author</th><th>Expected</th><th>Actual</th></tr></thead>
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
            </div>
          )}
        </section>
      )}

      {step === "engine" && (
        <section key="engine" className="step-pane flex-1 min-h-0 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3 shrink-0">
            <p className="text-sm text-stone-700">Hover a node for the clause, formula, and ledger. Click a rule to edit it. A live edit becomes the next draft and does not replace the running engine until you approve it.</p>
            <button
              className="btn btn-primary shrink-0"
              disabled={!pack.bundle || openRebates.length > 0 || Boolean(busy)}
              onClick={() => {
                setAcks([false, false, false]);
                setApproveOpen(true);
              }}
            >
              Approve rules engine
            </button>
          </div>
          {!pack.bundle && <p className="text-sm text-ink shrink-0">Process the documents first.</p>}
          {openRebates.length > 0 && <p className="text-sm text-ink shrink-0">Tick the open rebate boxes on Process before you approve.</p>}
          <RuleGraph documentId={params.id} refreshKey={refreshKey} />
        </section>
      )}

      {step === "live" && (
        <section key="live" className="step-pane flex-1 min-h-0 grid grid-cols-[360px_1fr] grid-rows-[minmax(0,1fr)] gap-3">
          <div className="min-h-0 grid grid-rows-[auto_minmax(0,1fr)] gap-2">
          <div className="panel p-3 flex flex-col gap-1.5">
            <h2 className="font-semibold text-sm">What this stream does</h2>
            <p className="text-xs text-stone-600">Each file is posted in order. A leak pulses red. A pass stays still.</p>
            {pack.supplier_key === "meridian-components" ? (
              <>
                <button className="btn btn-primary" disabled={playing || !live} onClick={() => playStream()}>
                  {playing && <span className="spinner" />}
                  {playing ? "Playing…" : "Play live stream"}
                </button>
                <button type="button" className="btn" onClick={() => setShowFiles(true)}>Show the files</button>
              </>
            ) : (
              <p className="text-xs text-stone-600">This workspace uses the form below. Load Meridian Components from the home page to play the prepared invoice stream.</p>
            )}
          </div>
          <div className="panel p-3 min-h-0 flex flex-col gap-1.5 overflow-hidden">
            <h2 className="font-semibold text-sm shrink-0">Check invoices</h2>
            <p className="text-xs text-stone-600 shrink-0">Paste an invoice, email, or spreadsheet, or drop the file. The model structures it, then the engine checks it.</p>
            <div className="min-h-0 flex flex-col gap-1.5 flex-1 overflow-hidden">
              <textarea
                className="field field-compact min-h-0 flex-1"
                placeholder="Paste the invoice as it arrived"
                value={invoiceText}
                onChange={(event) => setInvoiceText(event.target.value)}
              />
              <label
                className="text-xs text-stone-600 shrink-0"
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  const dropped = event.dataTransfer.files[0];
                  if (dropped) setInvoiceFile(dropped);
                }}
              >
                {invoiceFile ? invoiceFile.name : "Drop a PDF, text file, CSV, or email"}
                <input
                  className="mt-1 block w-full text-xs"
                  type="file"
                  accept=".txt,.csv,.pdf,.eml,text/plain,application/pdf,message/rfc822"
                  onChange={(event) => setInvoiceFile(event.target.files?.[0] || null)}
                />
              </label>
              <button className="btn btn-primary shrink-0" type="button" disabled={Boolean(busy) || (!invoiceText.trim() && !invoiceFile)} onClick={() => checkInvoice()}>
                {busy === "Checking the invoice" ? "Checking the invoice" : "Check invoice"}
              </button>
              <button type="button" className="text-left text-xs font-medium text-accent shrink-0" onClick={() => setShowPeriod((open) => !open)}>{showPeriod ? "Hide document upload" : "Add a document during the period"}</button>
              {showPeriod && (
                <div className="min-h-0 overflow-auto space-y-1.5">
              <input className="block w-full text-xs" type="file" accept=".txt,.csv,.pdf,.xlsx,.xlsm,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => { if (event.target.files) upload(event.target.files).then((stored) => { if (stored) setMessage("Document stored. Rebuild the draft when you want it in the engine."); }); }} />
              <button className="btn" disabled={Boolean(busy)} onClick={async () => {
                setBusy("Compiling the engine");
                try {
                  await api(`/v1/packs/${params.id}/process`, { method: "POST" });
                  setMessage("A new draft was compiled. The live engine keeps running until you approve the draft.");
                  await load();
                } catch {
                  setMessage("");
                } finally {
                  setBusy("");
                }
              }}>Rebuild draft from documents</button>
                </div>
              )}
            </div>
          </div>
          </div>
          <RuleGraph documentId={params.id} refreshKey={refreshKey} live={showFlow} spotlight={spotlight} />
        </section>
      )}
      {approveOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-6">
          <form
            className="panel w-full max-w-lg p-5 space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!pack.bundle || acks.some((ack) => !ack)) return;
              setBusy("Approving the engine");
              try {
                await api(`/v1/bundles/${pack.bundle.bundle_id}/approve`, { method: "POST", body: JSON.stringify({ human_switches: {} }) });
                setMessage("Engine approved. Live transactions now use this version.");
                setApproveOpen(false);
                await load();
                setLive(true);
                setStep("live");
              } catch {
                setMessage("");
              } finally {
                setBusy("");
              }
            }}
          >
            <h2 className="text-lg font-semibold">Approve the rules engine</h2>
            <p className="text-sm text-stone-700">Tick each line. Approval stays closed until all three are checked.</p>
            {["I have read the rules on this graph.", "I understand these rules were drafted by software from the uploaded documents, and a person must confirm them.", "I understand that after approval, live invoices are checked against this version."].map((line, index) => (
              <label key={line} className="flex items-start gap-2 text-sm font-medium text-ink">
                <input type="checkbox" className="mt-1" checked={acks[index]} onChange={(event) => setAcks(acks.map((ack, ackIndex) => ackIndex === index ? event.target.checked : ack))} />
                <span>{line}</span>
              </label>
            ))}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn" onClick={() => setApproveOpen(false)}>Cancel</button>
              <button className="btn btn-primary" type="submit" disabled={acks.some((ack) => !ack) || Boolean(busy)}>
                {busy === "Approving the engine" && <span className="spinner" />}
                {busy === "Approving the engine" ? "Approving the engine" : "Approve"}
              </button>
            </div>
          </form>
        </div>
      )}
      {showFiles && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-6">
          <div className="panel w-full max-w-lg max-h-[70vh] overflow-auto p-5 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Stream files</h2>
              <button type="button" className="btn" onClick={() => setShowFiles(false)}>Close</button>
            </div>
            <ol className="space-y-2 text-sm">
              {stream.map((file) => (
                <li key={file.filename}>
                  <div className="font-medium">{file.filename}</div>
                  <div className="text-stone-600">{file.summary}</div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </div>
    {processing && (
      <div className="ai-veil" role="alertdialog" aria-modal="true" aria-labelledby="ai-working-title">
        <div className="ai-card">
          <div className="ai-radar" aria-hidden="true">
            <span className="ai-ring" />
            <span className="ai-ring" />
            <span className="ai-ring" />
            <span className="ai-sweep" />
            <span className="ai-core" />
          </div>
          <div className="ai-kicker">Processing</div>
          <h2 id="ai-working-title" className="ai-title">{processing.title}</h2>
          <p className="ai-detail">{processing.detail}</p>
          {(busy === "Compiling the engine" || busy === "Checking the invoice") && (
            <div className="ai-meter" aria-hidden="true">
              <span style={{ width: `${meter}%` }} />
            </div>
          )}
        </div>
      </div>
    )}
    </>
  );
}
