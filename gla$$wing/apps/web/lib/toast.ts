"use client";

export type Toast = { id: number; message: string };

type Listener = (toasts: Toast[]) => void;

let toasts: Toast[] = [];
const listeners = new Set<Listener>();

function publish() {
  for (const listener of listeners) listener(toasts);
}

export function warn(message: string) {
  const id = Date.now() + Math.random();
  toasts = [...toasts, { id, message }];
  publish();
  window.setTimeout(() => dismiss(id), 7000);
}

export function dismiss(id: number) {
  toasts = toasts.filter((toast) => toast.id !== id);
  publish();
}

export function subscribe(listener: Listener) {
  listeners.add(listener);
  listener(toasts);
  return () => listeners.delete(listener);
}
