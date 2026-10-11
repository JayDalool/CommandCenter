/** DevTrail: the Roles line only where roles were recorded, and the pipeline verdict beats GitHub's review. */
import { render, screen } from "@testing-library/react";
import { DevTrail, reviewCell } from "../src/components/DevTrail";
import type { DevRow } from "../src/api/types";

function row(over: Partial<DevRow> = {}): DevRow {
  return { key: "SV-056", project: "samvision", title: "Valuation", status: "IN_REVIEW", priority: "P2", assignee: null,
    flags: [], updatedAt: 1, branch: null, prs: [], pr: null, commits: null, ci: null, review: "APPROVED",
    merge: null, verify: null, deploy: null, ...over } as DevRow;
}

it("has no Roles line without recorded roles", () => {
  render(<DevTrail row={row()} />);
  expect(screen.queryByText("Roles")).toBeNull();
  render(<DevTrail row={row({ roles: {} })} />);
  expect(screen.queryByText("Roles")).toBeNull();
});

it("shows the recorded roles in pipeline order", () => {
  render(<DevTrail row={row({ roles: { planner: { model: "opus", at: 1 }, implementer: { model: "sonnet", at: 2 },
    reviewer: { model: "opus", at: 3 } } })} />);
  expect(screen.getByText("Roles")).toBeInTheDocument();
  expect(screen.getByText("planner opus · implementer sonnet · reviewer opus")).toBeInTheDocument();
});

it("prefers the pipeline review verdict, and falls back to GitHub's", () => {
  const head = "94abcdef0123456789";
  const { unmount } = render(<DevTrail row={row({ review: "CHANGES_REQUESTED", pipelineReview: { verdict: "APPROVE", head } })} />);
  expect(screen.getByText("approved at 94abcde")).toHaveClass("ok-t");
  expect(screen.queryByText("CHANGES REQUESTED")).toBeNull();
  unmount();
  const r2 = render(<DevTrail row={row({ pipelineReview: { verdict: "REQUEST_CHANGES", head } })} />);
  expect(screen.getByText("changes requested at 94abcde")).toHaveClass("warn-t");
  r2.unmount();
  render(<DevTrail row={row({ pipelineReview: null })} />);
  expect(screen.getByText("APPROVED")).toBeInTheDocument();
});

it("falls back to GitHub's review when the pipeline recorded a head but no verdict", () => {
  render(<DevTrail row={row({ pipelineReview: { verdict: null, head: "94abcdef0123456789" } })} />);
  expect(screen.getByText("APPROVED")).toBeInTheDocument();
});

it("the Development table's Review cell shows the pipeline verdict, not GitHub's PENDING", () => {
  render(<div>{reviewCell(row({ review: "REVIEW_REQUIRED", pipelineReview: { verdict: "APPROVE", head: "94abcdef0123456789" } }))}</div>);
  expect(screen.getByText("approved at 94abcde")).toBeInTheDocument();
  expect(screen.queryByText("PENDING")).toBeNull();
});
