"use client";

import { useEffect, useState } from "react";
import { dismiss, subscribe, type Toast } from "@/lib/toast";

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => subscribe(setToasts), []);
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="toast-warn" role="status">
          <div>
            <div className="toast-kicker">Warning</div>
            <p>{toast.message}</p>
          </div>
          <button type="button" className="toast-close" aria-label="Dismiss warning" onClick={() => dismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
