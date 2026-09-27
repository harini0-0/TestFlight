"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { login } from "@/lib/api";
import { LogoMark, NavIcon, type NavIconName } from "@/components/Logo";
import { Toaster } from "@/components/Toaster";

const links: Array<[string, string, NavIconName]> = [
  ["Workspace", "/", "workspace"],
  ["Findings", "/findings", "findings"],
  ["Value", "/roi", "value"],
  ["Audit", "/audit", "audit"],
  ["Admin", "/admin", "admin"],
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const locked = path === "/" || path.startsWith("/work");
  return (
    <div className="h-screen overflow-hidden grid grid-cols-[248px_1fr] bg-paper text-ink">
      <aside className="h-full bg-[#1c1917] text-white px-4 py-6 flex flex-col gap-8">
        <Link href="/" className="block rounded-lg px-2 py-1 hover:bg-white/5">
          <span className="flex items-center gap-3">
            <LogoMark className="h-11 w-11 shrink-0" />
            <span className="text-[15px] font-semibold leading-[1.15] tracking-tight">Accio Rebate</span>
          </span>
          <span className="mt-2.5 block text-xs leading-4 text-slate-400">Contract rules, enforced live</span>
        </Link>
        <nav className="flex flex-col gap-1 text-sm">
          {links.map(([label, href, icon]) => {
            const active = href === "/" ? path === "/" || path.startsWith("/work") : path.startsWith(href);
            return (
              <Link key={href} href={href} className={active ? "flex items-center gap-2.5 rounded-md bg-white/10 px-3 py-2 text-white" : "flex items-center gap-2.5 rounded-md px-3 py-2 text-slate-300 hover:text-white"}>
                <NavIcon name={icon} />
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
      <main className={locked ? "min-w-0 h-full overflow-hidden p-5" : "min-w-0 h-full overflow-auto p-5"}>{children}</main>
      <Toaster />
    </div>
  );
}
