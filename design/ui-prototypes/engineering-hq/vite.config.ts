/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ISOLATED prototype. Loopback only, no proxy, no /api: it never talks to ccd, herdr or production.
export default defineConfig({
  plugins: [react()],
  base: "./",   // relative asset paths, so the build also runs from a static copy
  server: { host: "127.0.0.1", port: 5180, strictPort: true },
  preview: { host: "127.0.0.1", port: 5181, strictPort: true },
  build: { target: "es2022", sourcemap: false },
  test: { environment: "jsdom", globals: true, setupFiles: ["./tests/setup.ts"], include: ["tests/**/*.test.{ts,tsx}"] },
});
