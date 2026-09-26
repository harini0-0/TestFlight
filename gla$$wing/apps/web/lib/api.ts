import { warn } from "@/lib/toast";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const warnings: Record<string, string> = {
  "resolve ambiguous fields before approval": "Confirm the open fields, including how each rebate applies, before you approve the engine.",
  "template tests are failing": "Template tests are failing. Review the results before approval.",
  "template cases cannot be waived": "Template tests cannot be waived. Fix the failing case before approval.",
  "upload at least one document": "Upload at least one document before processing.",
  "only a draft can be edited before approval": "Only a draft can be edited before approval.",
  "transaction id already used": "That invoice number was already checked. Use a new invoice number.",
  "human review can be required only on a warned clause": "A person can be required only on a warned clause.",
  "this stream belongs to the Meridian Components workspace": "This stream belongs to the Meridian Components workspace.",
  "approve the engine before playing the live stream": "Approve the engine before playing the live stream.",
  "the language model is not configured": "Set the model key and base URL before checking an unstructured invoice.",
  "GLASSWING_LLM_BASE_URL is not set": "Set the model base URL before checking an unstructured invoice.",
  "the model rejected the API key": "The model rejected the API key.",
  "no text could be read from the invoice": "No text could be read from that invoice.",
};

export function plainError(raw: string, fallback: string): string {
  const text = raw.trim();
  if (!text) return fallback;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return warnings[detail] || sentence(detail);
    if (Array.isArray(detail)) {
      const parts = detail.map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
        return "";
      }).filter(Boolean);
      if (parts.length) return sentence(parts.join(" "));
    }
  } catch {
    return text.startsWith("{") ? fallback : sentence(text);
  }
  return sentence(text);
}

function sentence(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

export function fail(raw: string, fallback: string): never {
  const message = plainError(raw, fallback);
  warn(message);
  throw new Error(message);
}

export function token(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("glasswing_token") || "";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token()}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) fail(await response.text(), response.statusText || "The request failed");
  return response.json() as Promise<T>;
}

export async function login(role: string, sub: string): Promise<void> {
  const response = await fetch(`${API_URL}/v1/auth/dev-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sub, tenant_id: "demo", role }),
  });
  if (!response.ok) fail(await response.text(), "Sign-in failed");
  const body = (await response.json()) as { access_token: string };
  localStorage.setItem("glasswing_token", body.access_token);
  localStorage.setItem("glasswing_role", role);
}
