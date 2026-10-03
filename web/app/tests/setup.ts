import "@testing-library/jest-dom/vitest";

// jsdom lacks these browser APIs.
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || function () {};
if (!(globalThis as { CSS?: unknown }).CSS) (globalThis as { CSS?: unknown }).CSS = { escape: (s: string) => s.replace(/["\\]/g, "\\$&") };
