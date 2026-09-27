"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Pack = { pack_id: string; supplier_key: string; status: string };

export default function ContractsPage() {
  const [packs, setPacks] = useState<Pack[]>([]);
  useEffect(() => {
    api<{ packs: Pack[] }>("/v1/packs").then((body) => setPacks(body.packs)).catch(() => undefined);
  }, []);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Workspaces</h1>
      <ul className="space-y-2">
        {packs.map((pack) => (
          <li key={pack.pack_id} className="panel px-4 py-3 flex justify-between">
            <span>{pack.supplier_key} · {pack.status}</span>
            <Link className="text-accent text-sm font-medium" href={`/work/${pack.pack_id}`}>Open</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
