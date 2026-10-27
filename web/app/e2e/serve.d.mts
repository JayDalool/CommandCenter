// Types for serve.mjs, for the TypeScript that imports it (tests/e2e-serve.test.ts, e2e/serve.spec.ts).
export function csp(port: number): string;
export function securityHeaders(port: number): Record<string, string>;
export const HASHED_ASSET: RegExp;
export const CACHE_IMMUTABLE: string;
export const CACHE_REVALIDATE: string;
export function createServer(dist: string, port: number): unknown;
