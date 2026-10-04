/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` serves on 127.0.0.1:5173 and proxies /api to a ccd
// (CCD_URL, default the dev instance on 127.0.0.1:7788). The proxy only rewrites
// Host/Origin so ccd's same-origin checks pass; the token still comes from the
// browser, so nothing reachable on 5173 is authenticated by the proxy itself.
// Production: ccd serves dist/ itself, same origin, no proxy.
const ccd = process.env.CCD_URL ?? "http://127.0.0.1:7788";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: ccd,
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (req) => req.setHeader("origin", ccd));
          proxy.on("proxyReqWs", (req) => req.setHeader("origin", ccd));
        },
      },
    },
  },
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 400 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
