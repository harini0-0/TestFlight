"use client";

import { useEffect, useState } from "react";
import { LogoMark } from "@/components/Logo";
import { api } from "@/lib/api";

type AuditEvent = { seq: number; prev_hash: string; row_hash: string; event: { action: string; actor: string } };

const actions: Record<string, string> = {
  "pack.created": "Workspace opened",
  "pack.file_stored": "Document stored",
  "bundle.compiled": "Engine compiled",
  "tests.ran": "Tests ran",
  "bundle.approved": "Engine approved",
  "finding.confirmed": "Finding confirmed",
  "finding.dismissed": "Finding dismissed",
};

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  useEffect(() => {
    api<{ events: AuditEvent[] }>("/v1/audit").then((body) => setEvents(body.events)).catch(() => setEvents([]));
  }, []);
  const rows = events || [];
  return (
    <div className="space-y-4 max-w-3xl">
      <header className="flex items-start gap-3.5">
        <LogoMark className="mt-0.5 h-11 w-11 shrink-0" />
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Audit</h1>
          <p className="text-sm text-slate-600">Every approval, upload, and finding decision is stored in order. Each row carries the hash of the previous row, so a missing or altered step breaks the chain. The short codes below are the start of those hashes.</p>
        </div>
      </header>
      {events && rows.length === 0 && (
        <div className="panel p-5 text-sm text-slate-600">
          <p className="font-medium text-slate-800">No actions recorded yet.</p>
          <p className="mt-2">Open a workspace or load Meridian Components. Compiling and approving an engine writes the first rows.</p>
        </div>
      )}
      {rows.length > 0 && (
        <ol className="space-y-2 text-sm">
          {rows.map((row) => (
            <li key={row.seq} className="panel p-3">
              <div className="font-medium">{actions[row.event.action] || row.event.action}</div>
              <div className="text-slate-600">By {row.event.actor} · step {row.seq}</div>
              <div className="text-slate-500 break-all mt-1">{row.prev_hash.slice(0, 12)} → {row.row_hash.slice(0, 12)}</div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
