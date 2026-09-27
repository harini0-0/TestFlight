export function money(value: string | number | null | undefined): string {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

export function meterPercent(balance: string | number, threshold: string | number | null): number {
  const line = Number(threshold || 0);
  if (!line) return 0;
  return Math.max(0, Math.min(100, (Number(balance) / line) * 100));
}
