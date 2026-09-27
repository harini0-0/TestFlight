"use client";

import { useId } from "react";

export function LogoMark({ className = "h-10 w-10" }: { className?: string }) {
  const raw = useId().replace(/:/g, "");
  const bg = `${raw}-bg`;
  const brass = `${raw}-brass`;
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={bg} x1="4" y1="2" x2="36" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#3a5274" />
          <stop offset="1" stopColor="#182536" />
        </linearGradient>
        <linearGradient id={brass} x1="21" y1="6" x2="34" y2="18" gradientUnits="userSpaceOnUse">
          <stop stopColor="#f3ddb0" />
          <stop offset="1" stopColor="#c4923f" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="12" fill={`url(#${bg})`} />
      <rect x="0.6" y="0.6" width="38.8" height="38.8" rx="11.4" fill="none" stroke="white" strokeOpacity="0.16" />
      <path d="M11.6 30.8 27.2 13.2" fill="none" stroke="#fffaf3" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M11.2 31.2 16.4 25.4" fill="none" stroke="#c4893a" strokeWidth="3.4" strokeLinecap="round" />
      <circle cx="10.7" cy="31.7" r="1.45" fill="#e8c98a" />
      <path d="M15.6 26.2 17.6 24" fill="none" stroke="#f3ddb0" strokeWidth="2.7" strokeLinecap="round" />
      <path
        d="M27.5 5.8 29 10.1 33.6 10.2 29.9 13 31.3 17.4 27.5 14.8 23.7 17.4 25.1 13 21.4 10.2 26 10.1Z"
        fill={`url(#${brass})`}
      />
      <path d="M33.8 20.4 34.35 21.85 35.85 22.4 34.35 22.95 33.8 24.4 33.25 22.95 31.75 22.4 33.25 21.85Z" fill="#f7f3ea" />
      <circle cx="19.2" cy="15.4" r="0.7" fill="#f6e2b8" />
    </svg>
  );
}

const navIcons = {
  workspace: (
    <>
      <path d="M4.2 8.2h11.6v8.2a1.4 1.4 0 0 1-1.4 1.4H5.6a1.4 1.4 0 0 1-1.4-1.4V8.2Z" />
      <path d="M7.2 8.1V6.7A1.2 1.2 0 0 1 8.4 5.5h3.2a1.2 1.2 0 0 1 1.2 1.2v1.4" />
      <path d="M4.2 11.2h11.6" />
    </>
  ),
  findings: (
    <>
      <circle cx="10" cy="10" r="6.2" />
      <path d="M10 7.3v3.5" />
      <path d="M10 13.15h.01" />
    </>
  ),
  value: (
    <>
      <path d="M4.2 15.8V10.4" />
      <path d="M8.1 15.8V7.2" />
      <path d="M12 15.8V9.1" />
      <path d="M15.8 15.8V5.4" />
    </>
  ),
  audit: (
    <>
      <path d="M8.4 11.6 6.9 13.1a2.7 2.7 0 0 1-3.8-3.8L4.6 7.8" />
      <path d="M11.6 8.4 13.1 6.9a2.7 2.7 0 0 1 3.8 3.8L15.4 12.2" />
      <path d="M8.2 11.8 11.8 8.2" />
    </>
  ),
  admin: (
    <>
      <path d="M3.8 6.4h12.4" />
      <path d="M3.8 13.6h12.4" />
      <circle cx="8" cy="6.4" r="1.7" fill="currentColor" stroke="none" />
      <circle cx="12.6" cy="13.6" r="1.7" fill="currentColor" stroke="none" />
    </>
  ),
} as const;

export type NavIconName = keyof typeof navIcons;

export function NavIcon({ name }: { name: NavIconName }) {
  return (
    <svg viewBox="0 0 20 20" className="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {navIcons[name]}
    </svg>
  );
}
