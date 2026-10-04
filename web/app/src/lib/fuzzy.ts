/**
 * Rank a candidate against a query: exact key match > prefix > word prefix >
 * substring > subsequence. Returns 0 for no match. Small and predictable on purpose.
 */
export function score(query: string, text: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const t = text.toLowerCase();
  if (t === q) return 1000;
  if (t.startsWith(q)) return 800 - t.length;
  const words = t.split(/[\s·/:#._-]+/);
  if (words.some((w) => w.startsWith(q))) return 600 - t.length;
  const i = t.indexOf(q);
  if (i >= 0) return 400 - i;
  let j = 0, gaps = 0, last = -1;
  for (let k = 0; k < t.length && j < q.length; k++) {
    if (t[k] === q[j]) { if (last >= 0) gaps += k - last - 1; last = k; j++; }
  }
  return j === q.length ? Math.max(1, 200 - gaps * 4) : 0;
}

/** Every word of the query must match somewhere; the score is the sum. */
export function scoreAll(query: string, fields: string[]): number {
  const words = query.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return 1;
  let total = 0;
  for (const w of words) {
    const best = Math.max(0, ...fields.map((f) => score(w, f)));
    if (!best) return 0;
    total += best;
  }
  return total;
}
