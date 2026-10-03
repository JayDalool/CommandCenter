# web/

- `app/` — the Command Center UI (P4B). React + TypeScript + Vite; the only
  runtime dependencies are `react` and `react-dom`. ccd serves `app/dist` from
  its own origin. `npm run build`, `npm test`, `npm run dev` (Vite on
  127.0.0.1:5173 proxying `/api` to the dev ccd on 127.0.0.1:7788). Design:
  `src/styles/tokens.css`; architecture: `../docs/ARCHITECTURE.md`.
- `prototypes/` — the P4A review (A Operator, B Studio, C Terminal+). Jay chose
  B as the structure with A's density and C's personality; kept for reference.
