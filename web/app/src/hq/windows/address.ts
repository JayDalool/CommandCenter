// The address of an HQ pop-out window, kept apart from manager.ts so Classic's bundle can recognise one without
// loading the window manager. A pop-out's address is #/pop/<view> and nothing else: no id, no parameters.
export const POP_VIEWS = ["dashboard", "needs", "agents", "projects", "tasks", "activity", "approvals", "budgets"] as const;
export type PopView = (typeof POP_VIEWS)[number];
export const isPopView = (v: unknown): v is PopView => typeof v === "string" && (POP_VIEWS as readonly string[]).includes(v);

export const POP_HASH = /^#\/pop\/(dashboard|needs|agents|projects|tasks|activity|approvals|budgets)$/;
export const popViewOf = (hash: string): PopView | null => (POP_HASH.exec(hash)?.[1] as PopView | undefined) ?? null;
export const popHash = (v: PopView) => `#/pop/${v}`;
