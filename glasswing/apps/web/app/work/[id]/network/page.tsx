"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ClauseWeb } from "@/components/ClauseWeb";
import { api } from "@/lib/api";

type Pack = { supplier_key: string };

export default function NetworkPage() {
  const params = useParams<{ id: string }>();
  const [pack, setPack] = useState<Pack | null>(null);

  useEffect(() => {
    api<Pack>(`/v1/packs/${params.id}`)
      .then(setPack)
      .catch(() => undefined);
  }, [params.id]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <header className="flex items-end justify-between gap-6 shrink-0">
        <div>
          <div className="text-xs uppercase tracking-wide text-stone-500">Clause network</div>
          <h1 className="text-2xl font-semibold tracking-tight mt-1">{pack?.supplier_key || "Workspace"}</h1>
          <p className="text-sm text-stone-600 mt-1">How the documents in this workspace point at each other. An edge means one clause depends on another document, so a change on one side may strand the other.</p>
        </div>
        <Link className="btn shrink-0" href={`/work/${params.id}`}>Back to workspace</Link>
      </header>
      <div className="step-pane flex-1 min-h-0">
        <ClauseWeb documentId={params.id} />
      </div>
    </div>
  );
}
