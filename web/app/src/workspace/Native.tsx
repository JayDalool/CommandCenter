// NATIVE TERMINALS — the optional ⋯ "Open in Windows Terminal": a real Windows
// Terminal tab over Jay's own SSH (the browser terminal is the default). The page
// only offers a commandcenter:// link naming an ACTION and a registered project PREFIX; CommandCenter.exe (0.3.0+)
// resolves everything else itself, and jay-server's scripts/cc-terminal resolves
// the path or the coordinator from the project registry. No command, path, host
// or token ever travels in the link.

export type NativeAction = "claude" | "repo" | "server";
const PREFIX_RE = /^[A-Z][A-Z0-9]{1,5}$/;

/** The only links this page can hand to the Windows launcher. */
export function nativeUri(action: NativeAction, prefix?: string | null): string | null {
  if (action === "server") return "commandcenter://terminal/server";
  if (!prefix || !PREFIX_RE.test(prefix)) return null;
  return `commandcenter://terminal/${action}?project=${prefix}`;
}
