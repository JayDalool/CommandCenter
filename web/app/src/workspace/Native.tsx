// NATIVE TERMINALS — the recommended way to work interactively: a real Windows
// Terminal tab over Jay's own SSH. The page only offers a commandcenter:// link
// naming an ACTION and a registered project PREFIX; CommandCenter.exe (0.3.0+)
// resolves everything else itself, and jay-server's scripts/cc-terminal resolves
// the path or the coordinator from the project registry. No command, path, host
// or token ever travels in the link.
import type { ReactNode } from "react";

export type NativeAction = "claude" | "repo" | "server";
const PREFIX_RE = /^[A-Z][A-Z0-9]{1,5}$/;

/** The only links this page can hand to the Windows launcher. */
export function nativeUri(action: NativeAction, prefix?: string | null): string | null {
  if (action === "server") return "commandcenter://terminal/server";
  if (!prefix || !PREFIX_RE.test(prefix)) return null;
  return `commandcenter://terminal/${action}?project=${prefix}`;
}

export function NativeButton({ action, prefix, children, primary = true, small = false }: {
  action: NativeAction; prefix?: string | null; children: ReactNode; primary?: boolean; small?: boolean;
}) {
  const uri = nativeUri(action, prefix);
  if (!uri) return null;
  return <a className={`btn${primary ? " is-jay" : ""}${small ? " is-sm" : ""}`} href={uri}
    title="Opens a Windows Terminal tab over SSH (needs CommandCenter.exe 0.3.0 on this PC)">{children}</a>;
}

/** The repo / server terminal panel: native first, the browser shell on request. */
export function NativePanel({ action, prefix, label, detail, onBrowser }: {
  action: "repo" | "server"; prefix?: string | null; label: string; detail: string; onBrowser: () => void;
}) {
  return <div className="native">
    <div className="native-card">
      <div className="row" style={{ gap: 8 }}><span className="ro-tag is-live">RECOMMENDED</span><span className="caps muted">{label}</span></div>
      <NativeButton action={action} prefix={prefix}>{action === "repo" ? "Open native repo terminal" : "Open native server terminal"}</NativeButton>
      <div className="mono-xs muted">{detail}</div>
      <p className="text2 native-note">A Windows Terminal tab over your own SSH to jay-server — full keyboard, scrollback and colour.
        The first time, the browser asks to open CommandCenter.exe: allow it (tick “always”).</p>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="btn is-quiet is-sm" onClick={onBrowser}>Browser shell instead</button>
        <span className="mono-xs faint">runs in this page; needs Developer Mode</span>
      </div>
    </div>
  </div>;
}
