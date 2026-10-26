// Theme preference: Dark (the approved default), Light (optional design variant) or follow the system.
// Shared by every window of this browser, so a pop-out on another monitor switches with the main window.
// CSS reads <html data-hq-theme="dark|light">; the light tokens live in styles/theme-light.css.
// HQ has its own attribute, so a host page's or Classic's data-theme can never switch it by accident.
// `?theme=light|dark|system` in the address sets it too (used by the screenshot gallery).
import { SharedStore } from "./shared";

export type ThemePref = "dark" | "light" | "system";
const isPref = (v: unknown): v is ThemePref => v === "dark" || v === "light" || v === "system";
export const themePref = new SharedStore<ThemePref>("theme", "dark", isPref);

const mq: MediaQueryList | null = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: light)") : null;
/** What is showing now: the system choice resolves to light only when the OS asks for light. */
export function resolvedTheme(p: ThemePref = themePref.get(), osPrefersLight = !!mq?.matches): "dark" | "light" { return p === "system" ? (osPrefersLight ? "light" : "dark") : p; }

function apply() {
  if (typeof document === "undefined") return;
  const t = resolvedTheme();
  document.documentElement.dataset.hqTheme = t;
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", t);
}
try { const q = new URLSearchParams(location.search).get("theme"); if (isPref(q)) themePref.set(q); } catch { /* no URL */ }
apply();
themePref.subscribe(apply);
mq?.addEventListener?.("change", apply);
export function setThemePref(p: ThemePref) { themePref.set(p); }
