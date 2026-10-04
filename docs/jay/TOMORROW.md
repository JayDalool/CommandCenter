# Jay — Tomorrow

## Must do

No owner must-dos left: the herdr restart is done and verified (2026-10-03).

## Decisions needed

- [ ] Deploy P4B to the live ccd (restarts ccd, ends the P2 soak window)
  Options: (A) after the soak reaches 24 h (22:56 today), merge PR #1 and `systemctl --user restart ccd`; (B) now; (C) keep testing on the preview first.
  Recommendation: A. herdr is back under systemd (verified 2026-10-03); let the soak reach 24 h with agents running, then deploy.

- [ ] Task migration preview — three calls before any import
  Options: P0/P1/P2/P3 → URGENT/HIGH/MEDIUM/LOW (current mapping) or all P-levels → MEDIUM; import DONE/DENIED history (current: yes, 149 tickets) or open work only; GYST OPS1 (`PENDING (operator)`) and VN-009 (no status line) → PROPOSED or skip.
  Recommendation: keep the mapping, import history, both ambiguous ones as PROPOSED. Nothing is imported until you say so.

## UI review

- [ ] New Command Center UI (fake herdr, seeded tickets — not your live data)
  URL: http://127.0.0.1:7788 after `ssh -N -L 7788:127.0.0.1:7788 jay-server`; token: `ssh jay-server cat command-center/dev/ccd.token | clip`
  What to check: Overview answers the five questions; Tasks (N to capture, Pipeline, Needs Jay, open SV-056 detail); Workspaces (Command Center tab map, click gauzemate → blocked question); `` ` `` opens the read-only console; Ctrl+K "samv"; Light mode (top bar); 28 px rows (Settings). No browser was run on the server, so this is the first visual check.

## Optional

- [ ] Review draft PR #1 — https://github.com/JayDalool/CommandCenter/pull/1 (two independent reviews done, all findings fixed)
- [ ] Try the Windows launcher: `scripts/windows/CommandCenter.ps1` (tunnel with auto-reconnect, token to clipboard, opens the browser). Windows clipboard history may keep the token; turn history off or clear it.
- [ ] Stop the preview when done: `systemctl --user stop cc-dev-preview`
