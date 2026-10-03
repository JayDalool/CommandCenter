# web/

The browser UI. **Not started** — it is phase P4 and waits on Jay.

It will be built against the frozen API in `../docs/API.md`, served through
`ssh -L 7777:127.0.0.1:7777 jay-server`. Browser first; Tauri only after the
browser UI is accepted; no Electron.
