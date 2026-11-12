// The few environment variables the browser tests read (see README.md). Reached through globalThis so the type
// check needs no @types/node.
export const env = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;
