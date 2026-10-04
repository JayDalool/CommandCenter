// ccd sends epoch seconds; the browser counts milliseconds. Everything here takes seconds.
export const nowS = () => Date.now() / 1000;

export function dur(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h${String(m % 60).padStart(2, "0")}m`;
  return `${Math.floor(h / 24)}d`;
}

/** Short relative age: "12s", "4m", "3h", "2d". */
export function ago(at: number | null | undefined, now = nowS()): string {
  if (!at) return "—";
  const s = Math.max(0, now - at);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 172800) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function hms(at: number | null | undefined): string {
  if (!at) return "—";
  const d = new Date(at * 1000);
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

export function stamp(at: number | null | undefined): string {
  if (!at) return "—";
  const d = new Date(at * 1000);
  const date = d.toLocaleDateString("en-CA");
  return `${date} ${d.toLocaleTimeString("en-GB", { hour12: false, hour: "2-digit", minute: "2-digit" })}`;
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const g = n / 2 ** 30;
  return g >= 1 ? `${g.toFixed(1)}G` : `${Math.round(n / 2 ** 20)}M`;
}
