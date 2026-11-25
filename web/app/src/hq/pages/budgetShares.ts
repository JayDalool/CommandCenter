// The weekly budget's arithmetic for the page (CC-064 a). Money is whole cents and shares are whole percents, so the
// page never adds binary fractions. The server checks the same rules and is the one that decides.

/** "250", "250.5" or "250.50" as whole cents, or null for anything else (a sign, 3 decimals, text, empty). */
export function amountCents(text: string): number | null {
  const m = /^(\d{1,7})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!m) return null;
  const cents = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0") || 0);
  return cents > 0 && cents <= 100_000_000 ? cents : null;
}

/** Whole cents as the string the server takes: 25000 -> "250.00". */
export function centsText(cents: number): string {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

/** An app's share of the week, in cents, half up, as the server computes it. */
export function shareCents(totalCents: number, percent: number): number {
  return Math.floor((totalCents * percent + 50) / 100);
}

/** As even as whole percents allow, the first apps taking the extra points. */
export function evenShares(keys: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  keys.forEach((k, i) => { out[k] = Math.floor(100 / keys.length) + (i < 100 % keys.length ? 1 : 0); });
  return out;
}

/** One slider moved to `value`: the others share what is left in proportion to what they had (largest remainder, so
 *  the total stays exactly 100), or evenly when they had nothing. Moving a slider never changes it by itself. */
export function rebalance(shares: Record<string, number>, key: string, value: number): Record<string, number> {
  const keys = Object.keys(shares);
  const v = Math.max(0, Math.min(100, Math.round(value)));
  const others = keys.filter((k) => k !== key);
  if (!others.length) return { [key]: 100 };
  const left = 100 - v;
  const had = others.reduce((n, k) => n + shares[k], 0);
  const ideal = others.map((k) => had > 0 ? shares[k] * left / had : left / others.length);
  const floors = ideal.map(Math.floor);
  let spare = left - floors.reduce((n, x) => n + x, 0);
  // Largest fractional part first; ties go to the earlier app, so the result is the same every time.
  const order = ideal.map((x, i) => [x - Math.floor(x), i] as const).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (const [, i] of order) { if (spare <= 0) break; floors[i] += 1; spare -= 1; }
  const out: Record<string, number> = {};
  for (const k of keys) out[k] = k === key ? v : floors[others.indexOf(k)];
  return out;
}
