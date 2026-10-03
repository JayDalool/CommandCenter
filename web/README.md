# web/

The browser UI.

- `prototypes/` — **P4A design review**: three directions (A Operator, B Studio,
  C Terminal+) on one fixture, plain HTML/CSS/JS, no build, no CDN. Open
  `prototypes/index.html` through the preview server (`127.0.0.1:5173`, reached
  from Windows with `ssh -N -L 5173:127.0.0.1:5173 jay-server`).
  Check: `node prototypes/tests/render.test.js`.
- The real UI (P4B) starts only after Jay picks a direction. It will be built
  against the frozen API in `../docs/API.md`. Browser first; Tauri only after the
  browser UI is accepted; no Electron.
