"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { login } from "@/lib/api";
import { Toaster } from "@/components/Toaster";

const links = [
  ["Workspace", "/"],
  ["Findings", "/findings"],
  ["Value", "/roi"],
  ["Audit", "/audit"],
  ["Admin", "/admin"],
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="min-h-screen grid grid-cols-[240px_1fr] bg-paper text-ink">
      <aside className="bg-ink text-white px-5 py-6 flex flex-col gap-8">
        <div>
          <div className="text-[15px] font-semibold leading-5">AI procurement control</div>
          <div className="text-xs text-slate-400 mt-1">Contract rules, enforced live</div>
        </div>
        <nav className="flex flex-col gap-1 text-sm">
          {links.map(([label, href]) => {
            const active = href === "/" ? path === "/" || path.startsWith("/work") : path.startsWith(href);
            return (
              <Link key={href} href={href} className={active ? "rounded-md bg-white/10 px-3 py-2 text-white" : "rounded-md px-3 py-2 text-slate-300 hover:text-white"}>
                {label}
              </Link>
            );
          })}
        </nav>
          <button
          className="mt-auto mb-8 text-left text-xs leading-5 text-slate-400 hover:text-slate-200"
          onClick={() => login("procurement_manager", "manager").then(() => location.reload())}
        >
          Procurement manager
        </button>
      </aside>
      <main className="min-w-0 p-8">{children}</main>
      <Toaster />
    </div>
  );
}
