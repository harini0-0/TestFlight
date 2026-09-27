"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function AdminPage() {
  const [threshold, setThreshold] = useState("100000");
  const [minutes, setMinutes] = useState("6");
  const [message, setMessage] = useState("");
  useEffect(() => {
    api<{ high_value_threshold: string; review_minutes: string }>("/v1/admin/settings")
      .then((body) => {
        setThreshold(body.high_value_threshold);
        setMinutes(body.review_minutes);
      })
      .catch(() => setMessage("Settings could not be loaded. You can still type values and save."));
  }, []);
  return (
    <div className="space-y-4 max-w-xl">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Administration</h1>
        <p className="text-sm text-slate-600">These two numbers change how the engine warns you. They do not change a contracted price or a rebate rate.</p>
      </header>
      <section className="panel p-5 space-y-4">
        <label className="block text-sm">
          <span className="font-medium">High-value threshold</span>
          <p className="text-slate-600 mt-1 mb-2">A rule whose dollars sit at or above this amount is marked high value. A high-value rebate stays visible on the graph as a warning until someone confirms how it applies.</p>
          <input className="field" value={threshold} onChange={(event) => setThreshold(event.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="font-medium">Minutes saved per cleared invoice</span>
          <p className="text-slate-600 mt-1 mb-2">Used on the Value screen. Each invoice that passes every rule counts as this many minutes a person did not spend reviewing it.</p>
          <input className="field" value={minutes} onChange={(event) => setMinutes(event.target.value)} />
        </label>
        <button
          className="btn btn-primary"
          onClick={() => {
            api("/v1/admin/settings", { method: "PUT", body: JSON.stringify({ high_value_threshold: threshold, review_minutes: minutes }) })
              .then(() => setMessage("Saved. New compiles use the threshold. The Value screen uses the minutes."))
              .catch(() => setMessage(""));
          }}
        >
          Save
        </button>
        {message && <p className="text-sm text-slate-700">{message}</p>}
      </section>
    </div>
  );
}
