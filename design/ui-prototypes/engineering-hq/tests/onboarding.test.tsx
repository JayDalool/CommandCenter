// New Agent / New Project onboarding (Jay, 2026-10-22): templates, validation, duplicates, permissions,
// approval, lifecycle, cancellation, pop-outs and cross-page consistency. Mock data only.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { App, renderView } from "../src/App";
import { owners, popOut, deadOwners } from "../src/windows/manager";
import { chat, feed, viewState } from "../src/data/live";
import { AGENTS, CONVERSATIONS, INITIAL_AGENT_STATE, PROJECTS, SEED_CHAT, TASKS, agent, project } from "../src/data/seed";
import {
  activateAgent, agentDraftFrom, agentDraftOf, blankProjectDraft, createProject, currentProfile, offboard, org, reassign, seedOrg, setLife, updateAgent,
  type AgentDraft, type ProjectDraft,
} from "../src/data/org";
import { validateAgent, validateProject } from "../src/data/validate";
import { AGENT_TEMPLATES, PERMISSIONS, effective, projectRules } from "../src/data/catalog";

const go = (h: string) => act(() => { location.hash = h; window.dispatchEvent(new HashChangeEvent("hashchange")); });
let fetchSpy: ReturnType<typeof vi.fn>;
let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  org.set(seedOrg()); owners.set({}); viewState.set({}); chat.set(SEED_CHAT); sessionStorage.clear();
  feed.set({ agents: INITIAL_AGENT_STATE, beat: Date.now(), outage: false, source: "demo" });
  openSpy = vi.fn(() => ({ closed: false, focus: vi.fn(), close: vi.fn() }));
  vi.stubGlobal("open", openSpy);
  fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy);
  vi.stubGlobal("WebSocket", vi.fn());
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const o = () => org.get();
const mira = (patch: Partial<AgentDraft> = {}): AgentDraft => ({ ...agentDraftFrom("impl", "samvision"), name: "Mira", id: "mira", ...patch });
const listing = (patch: Partial<ProjectDraft> = {}): ProjectDraft => ({ ...blankProjectDraft(), name: "Listing Scraper", key: "listing-scraper", prefix: "LS", repo: "JayDalool/listing-scraper", lead: "claude", ...patch });
const msgs = (r: { errors: { msg: string }[] }) => r.errors.map((e) => e.msg).join(" | ");
const next = () => fireEvent.click(screen.getByRole("button", { name: /^Next:/ }));

describe("agent templates and validation", () => {
  it("offers the required templates, each with role, specialisation, model class, permissions and reporting", () => {
    for (const t of ["Project Lead", "Research / Planning Lead", "Implementation Agent", "Senior Code Reviewer", "UI Testing Lead", "DevOps / Release Lead",
      "Security Reviewer", "Architecture Reviewer", "Database Specialist", "Product / UX Researcher", "Documentation Agent"]) expect(AGENT_TEMPLATES.some((x) => x.title === t)).toBe(true);
    go("#/onboard"); render(<App />);
    const card = screen.getByRole("button", { name: "Senior Code Reviewer template" });
    expect(card).toHaveTextContent("GPT-5 Codex");
    expect(card).toHaveTextContent(/never merges/);
    expect(card).toHaveTextContent("The project lead");
    fireEvent.click(card);
    expect(screen.getByRole("button", { name: "Senior Code Reviewer template" })).toHaveAttribute("aria-pressed", "true");
  });

  it("a template fills safe defaults; custom starts read-only", () => {
    const d = agentDraftFrom("impl");
    expect(d.model).toBe("claude-sonnet-5-5");
    expect(d.grants["repo.commit"]).toBe("allow");
    expect(d.grants["repo.merge"]).toBe("deny");
    const c = agentDraftFrom("custom");
    expect(PERMISSIONS.filter((p) => c.grants[p.id] === "allow").map((p) => p.id).sort()).toEqual(["prod.observe", "repo.read"]);
  });

  it("requires a name, role, model, project, machine and mission, with readable messages", () => {
    const r = validateAgent({ ...mira(), name: "", id: "", title: "", model: "", project: "", machines: [], instructions: { ...mira().instructions, mission: "" } }, o());
    const m = msgs(r);
    for (const x of ["Give the agent a display name", "needs an ID", "role title", "Choose the model", "Choose the project", "at least one machine", "mission"]) expect(m).toContain(x);
    expect(m).not.toMatch(/undefined|schema|required property/i);
    expect(validateAgent(mira(), o()).errors).toEqual([]);
  });

  it("rejects duplicate names and IDs, reserved IDs, reused IDs of offboarded agents, and warns on confusable names", () => {
    expect(msgs(validateAgent(mira({ name: "nova" }), o()))).toContain("Nova already exists");
    expect(msgs(validateAgent(mira({ id: "nova" }), o()))).toContain(`already used by Nova`);
    expect(msgs(validateAgent(mira({ id: "admin" }), o()))).toContain("reserved");
    expect(msgs(validateAgent(mira({ id: "Bad ID" }), o()))).toContain("lowercase");
    expect(msgs(validateAgent(mira({ name: "Jay" }), o()))).toContain("reserved");
    expect(validateAgent(mira({ name: "Novaa" }), o()).warnings.map((w) => w.msg).join()).toContain("easy to confuse with Nova");
    act(() => offboard("pixel", "nova", "test"));
    expect(msgs(validateAgent(mira({ id: "pixel" }), o()))).toContain("never reused");
  });

  it("checks the project: it must exist, have one lead, and the manager must be on its team", () => {
    expect(msgs(validateAgent(mira({ project: "nope" }), o()))).toContain("doesn't exist");
    expect(msgs(validateAgent(mira({ reportsTo: "jay" }), o()))).toContain("already has a lead (Claude)");
    expect(msgs(validateAgent(mira({ project: "gyst", reportsTo: "atlas" }), o()))).toContain("on this project's team");
  });

  it("enforces fixed boundaries, project limits and machine eligibility", () => {
    expect(msgs(validateAgent(mira({ grants: { ...mira().grants, "repo.merge": "allow" } }), o()))).toContain("Jay merges every PR");
    expect(msgs(validateAgent(mira({ grants: { ...mira().grants, "infra.secrets": "approval" } }), o()))).toContain("Secrets stay in ccd");
    const over = validateAgent(mira({ grants: { ...mira().grants, "prod.deploy": "allow" } }), o());
    const e = over.errors.find((x) => x.field === "prod.deploy")!;
    expect(e.msg).toMatch(/Deploy/);
    expect(msgs(validateAgent(mira({ repos: ["JayDalool/gyst-lifeops"] }), o()))).toContain("not SamVision's repository");
    expect(validateAgent(mira({ machines: ["server", "laptop"] }), o()).errors.some((x) => x.msg.includes("not an eligible machine"))).toBe(true);
    expect(validateAgent(mira({ machines: ["laptop"] }), o()).errors.some((x) => x.msg.includes("None of the chosen machines"))).toBe(true);
  });

  it("effective access is the intersection: agent ∩ project ∩ worker ∩ task mode, never wider", () => {
    const g = mira().grants;
    const rules = projectRules({ preset: "standard", merge: "deny", deploy: "approval", prodWrite: "deny", migrations: "approval", downtime: "approval", browserProd: "deny", database: "deny", reviewers: 1, windows: [], tz: "x" });
    expect(effective("repo.commit", g, rules, ["server"], "assisted").result).toBe("allow");
    expect(effective("repo.commit", g, rules, ["server"], "manual").result).toBe("approval");
    expect(effective("run.browser", { ...g, "run.browser": "allow" }, rules, ["laptop"], "assisted").result).toBe("deny");
    expect(effective("repo.merge", { ...g, "repo.merge": "allow" }, rules, ["server"], "autonomous").result).toBe("deny");
    for (const p of PERMISSIONS) for (const m of ["manual", "assisted", "autonomous"] as const) {
      const r = effective(p.id, g, rules, ["server"], m).result;
      expect(["allow", "approval", "deny"].indexOf(r)).toBeGreaterThanOrEqual(["allow", "approval", "deny"].indexOf(g[p.id] ?? "deny"));
    }
  });
});

describe("New Agent wizard", () => {
  it("walks all ten steps, shows the review, and approves into mock state only", () => {
    go("#/onboard"); render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Implementation Agent template" }));
    next();
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Mira" } });
    expect(document.querySelector(".id-prev code")).toHaveTextContent("mira");
    for (let i = 0; i < 8; i++) next();
    expect(screen.getByRole("heading", { name: "Review & activate" })).toBeInTheDocument();
    expect(screen.getByLabelText("What this agent can do")).toHaveTextContent("Can modify SamVision development branches");
    expect(screen.getByLabelText("What this agent can do")).toHaveTextContent("Cannot merge");
    expect(screen.getByLabelText("What this agent can do")).toHaveTextContent("Cannot deploy");
    expect(screen.getByLabelText("What this agent can do")).toHaveTextContent("May use jay-server");
    fireEvent.click(screen.getByRole("button", { name: "Approve & Add Agent" }));
    const dlg = screen.getByRole("dialog", { name: "Approve and add Mira?" });
    expect(dlg).toHaveTextContent("No credentials");
    expect(o().agents.some((a) => a.id === "mira")).toBe(false);
    fireEvent.click(within(dlg).getByRole("button", { name: "Approve & Add Agent" }));
    expect(o().agents.find((a) => a.id === "mira")?.name).toBe("Mira");
    expect(o().audit.at(-1)?.kind).toBe("agent.activated");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(WebSocket).not.toHaveBeenCalled();
  });

  it("blocks approval while there are errors and links each error to its step", () => {
    go("#/onboard"); render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Custom agent template" }));
    fireEvent.click(screen.getByRole("button", { name: /Review & activate/ }));
    expect(screen.getByRole("button", { name: "Approve & Add Agent" })).toBeDisabled();
    const v = screen.getByRole("status", { name: "Validation" });
    expect(v).toHaveTextContent("Give the agent a display name");
    fireEvent.click(within(v).getAllByRole("button", { name: /Identity/ })[0]);
    expect(screen.getByRole("heading", { name: "Identity" })).toBeInTheDocument();
  });

  it("cancel with changes asks first and leaks nothing; Save Draft keeps a draft outside the roster", () => {
    const before = JSON.stringify({ a: o().agents, p: o().projects });
    go("#/onboard"); render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Implementation Agent template" }));
    next(); fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Ghost" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const dlg = screen.getByRole("dialog", { name: "Discard your changes?" });
    fireEvent.click(within(dlg).getByRole("button", { name: "Discard" }));
    expect(JSON.stringify({ a: o().agents, p: o().projects })).toBe(before);
    expect(viewState.get()["page:onboard"]?.draft ?? null).toBeNull();
    // save a draft
    go("#/onboard");
    fireEvent.click(screen.getByRole("button", { name: "Implementation Agent template" }));
    next(); fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Later" } });
    fireEvent.click(screen.getByRole("button", { name: /Save Draft/ }));
    expect(o().drafts).toHaveLength(1);
    expect(o().agents.some((a) => a.name === "Later")).toBe(false);
    go("#/agents");
    expect(screen.getByText("Later")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Later, / })).toBeNull();
  });
});

describe("after activation", () => {
  beforeEach(() => act(() => activateAgent(mira())));

  it("appears in Teams, the agent directory, Topology, Messages and search with a truthful status", () => {
    go("#/teams/samvision"); render(<App />);
    const node = screen.getByRole("button", { name: /^Mira, Implementation Agent/ });
    expect(node).toHaveTextContent("Not started");
    expect(node).not.toHaveTextContent("Working");
    go("#/agents");
    expect(screen.getByRole("button", { name: /^Mira, Implementation Agent/ })).toBeInTheDocument();
    expect(screen.getAllByText("No session events yet").length).toBeGreaterThan(0);
    go("#/messages/dm-mira");
    expect(document.querySelector(".thread-head")).toHaveTextContent("Mira");
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
    go("#/topology");
    act(() => viewState.set((s) => ({ ...s, "page:topology": { ...s["page:topology"], sel: "p:samvision", itab: "Team" } })));
    expect(screen.getByRole("button", { name: /^Mira, Implementation Agent/ })).toBeInTheDocument();
    expect(project("samvision").team.find((m) => m.id === "mira")?.reportsTo).toBe("claude");
  });

  it("shows the same name, role, colour and status on every page", () => {
    go("#/teams/samvision"); render(<App />);
    const seen: string[] = [];
    const grab = (el: Element) => seen.push(`${el.querySelector(".pres b")?.textContent}|${(el.querySelector(".av") as HTMLElement).style.getPropertyValue("--c")}`);
    grab(screen.getByRole("button", { name: /^Mira, Implementation Agent/ }));
    go("#/agents"); grab(screen.getByRole("row", { name: /Mira/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Mira, Implementation Agent/ }));
    grab(screen.getByRole("dialog", { name: "Agent details" }));
    expect(new Set(seen).size).toBe(1);
    expect(seen[0]).toBe(`Not started|${agent("mira").color}`);
  });

  it("edit renames without changing the ID, versions the config and keeps history attributed", () => {
    act(() => { TASKS[0].owner; });
    const d = { ...agentDraftOf("mira"), name: "Mira Prime", model: "claude-opus-5-5" };
    act(() => updateAgent(d));
    expect(agent("mira").name).toBe("Mira Prime");
    expect(o().agents.filter((a) => a.id === "mira")).toHaveLength(1);
    expect(o().profiles.mira.map((p) => p.version)).toEqual([1, 2]);
    expect(currentProfile("mira").model).toBe("claude-opus-5-5");
    expect(o().audit.at(-1)!.text).toContain("renamed Mira → Mira Prime");
    expect(CONVERSATIONS.find((c) => c.id === "dm-mira")?.title).toBe("Mira Prime");
  });

  it("pause and resume change what every page shows", () => {
    act(() => setLife("mira", "paused", "waiting for designs"));
    go("#/teams/samvision"); render(<App />);
    expect(screen.getByRole("button", { name: /^Mira, / })).toHaveTextContent("Paused");
    act(() => setLife("mira", "active"));
    expect(screen.getByRole("button", { name: /^Mira, / })).toHaveTextContent("Not started");
  });

  it("reassign moves it to another team and reporting line", () => {
    act(() => reassign("mira", "samvision", "gyst", "claude"));
    expect(project("samvision").team.some((m) => m.id === "mira")).toBe(false);
    expect(project("gyst").team.find((m) => m.id === "mira")?.reportsTo).toBe("claude");
  });

  it("offboarding keeps tasks, messages and audit attributed, hands work over and retires the ID", () => {
    const novaTasks = TASKS.filter((t) => t.owner === "nova" && t.stage !== "Closed").map((t) => t.key);
    act(() => offboard("nova", "mira", "replaced"));
    expect(agent("nova").name).toBe("Nova");                       // history still names it
    expect(agent("nova").life).toBe("offboarded");
    for (const k of novaTasks) { const t = TASKS.find((x) => x.key === k)!; expect(t.owner).toBe("mira"); expect(t.formerOwners).toContain("nova"); }
    expect(CONVERSATIONS.find((c) => c.id === "nova")?.archived).toBe(true);
    expect(chat.get().nova.length).toBeGreaterThan(0);              // messages are not deleted
    expect(PROJECTS.some((p) => p.team.some((m) => m.id === "nova"))).toBe(false);
    expect(o().audit.at(-1)!.text).toContain("History kept under ID nova");
    go("#/office"); render(<App />);
    expect(document.querySelectorAll(".agent-card").length).toBe(AGENTS.filter((a) => a.life !== "offboarded").length);
  });

  it("offboarding is confirmed in the inspector and needs the acknowledgement", () => {
    go("#/agents"); render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /^Mira, Implementation Agent/ }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Agent details" })).getByRole("button", { name: "Offboard" }));
    const dlg = screen.getByRole("dialog", { name: "Offboard Mira?" });
    expect(within(dlg).getByRole("button", { name: "Offboard Mira" })).toBeDisabled();
    fireEvent.click(within(dlg).getByRole("checkbox"));
    fireEvent.click(within(dlg).getByRole("button", { name: "Offboard Mira" }));
    expect(agent("mira").life).toBe("offboarded");
  });
});

describe("project validation", () => {
  it("requires the basics and rejects duplicate names, keys and prefixes", () => {
    expect(msgs(validateProject(blankProjectDraft(), o()))).toMatch(/Give the project a name.*needs a key.*ticket prefix/);
    expect(msgs(validateProject(listing({ name: "SamVision" }), o()))).toContain("already exists");
    expect(msgs(validateProject(listing({ key: "gyst" }), o()))).toContain("already used by GYST");
    expect(msgs(validateProject(listing({ prefix: "SV" }), o()))).toContain("Ticket keys would collide");
    expect(validateProject(listing(), o()).errors).toEqual([]);
  });

  it("rejects malformed repositories, URLs with credentials and repositories bound to another project", () => {
    expect(msgs(validateProject(listing({ repo: "not a repo" }), o()))).toContain("owner/name");
    expect(msgs(validateProject(listing({ repo: "https://tok123@github.com/JayDalool/x" }), o()))).toContain("never paste a URL that contains a token".replace("never", "Never"));
    expect(msgs(validateProject(listing({ repo: "JayDalool/SamVisionAI" }), o()))).toContain("already bound to SamVision");
  });

  it("enforces worker, profile and production rules", () => {
    expect(msgs(validateProject(listing({ type: "employer", workers: ["server"] }), o()))).toContain("may not use jay-server");
    expect(msgs(validateProject(listing({ type: "employer", target: "autonomous_product", workers: ["laptop"] }), o()))).toContain("Employer projects can only target");
    expect(msgs(validateProject(listing({ target: "restricted", taskMode: "autonomous" }), o()))).toContain("never more permissive");
    const prod = listing({ envs: { ...blankProjectDraft().envs, Production: { on: true, hosting: "", domain: "", deploy: "", database: "", health: "" } }, deploy: { ...listing().deploy, deploy: "allow" } });
    const r = validateProject(prod, o());
    expect(msgs(r)).toContain("Production needs protection");
    expect(r.errors.find((e) => e.msg.includes("Production needs protection"))!.fix).toBeTruthy();
    expect(validateProject(listing({ lead: "" }), o()).warnings.map((w) => w.msg).join()).toContain("No lead yet");
  });
});

describe("New Project wizard", () => {
  it("creates a mock project in Onboarding that appears on every page, with no external side effects", () => {
    go("#/newproject"); render(<App />);
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Listing Scraper" } });
    expect((screen.getByLabelText("Key") as HTMLInputElement).value).toBe("listing-scraper");
    expect((screen.getByLabelText("Ticket prefix") as HTMLInputElement).value).toBe("LS");
    next();
    fireEvent.click(screen.getByRole("radio", { name: /Propose a new repository/ }));
    expect(screen.getByText(/Requires Jay's authorisation/)).toBeInTheDocument();
    next(); next(); next();
    fireEvent.change(screen.getByLabelText("Project lead"), { target: { value: "claude" } });
    next();
    expect(screen.getByText("Starts in Onboarding / Observation")).toBeInTheDocument();
    next(); next(); next();
    fireEvent.click(screen.getByRole("button", { name: "Approve Mock Project" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: /Approve Listing Scraper/ })).getByRole("button", { name: "Approve Mock Project" }));
    const p = project("listing-scraper");
    expect(p.name).toBe("Listing Scraper");
    expect(p.health).toBe("onboarding");
    expect(p.repoState).toBe("proposed");
    expect(TASKS.find((t) => t.key === "LS-002")?.stage).toBe("Needs Jay");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
    // cross-page
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Listing Scraper");
    expect(document.querySelector(".onb-panel")).toHaveTextContent("Onboarding / Observation");
    expect(screen.getByRole("tab", { name: "Listing Scraper" })).toBeInTheDocument();
    go("#/office"); expect(screen.getByRole("button", { name: "Listing Scraper" })).toHaveTextContent("Onboarding");
    go("#/topology"); expect(screen.getByRole("button", { name: "Listing Scraper, onboarding" })).toBeInTheDocument();
    go("#/engineering"); expect(screen.getAllByText("LS-001").length).toBeGreaterThan(0);
    go("#/messages"); expect(screen.getByRole("link", { name: /# listing-scraper-team/ })).toBeInTheDocument();
    expect(document.documentElement.style.getPropertyValue("--pj-listing-scraper")).toBe(p.color);
  });

  it("plans a new agent from the Team step without losing the project draft", () => {
    go("#/newproject"); render(<App />);
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Listing Scraper" } });
    next(); fireEvent.change(screen.getByLabelText(/Repository \(owner/), { target: { value: "JayDalool/listing-scraper" } });
    fireEvent.click(within(screen.getByRole("navigation", { name: "Steps" })).getByRole("button", { name: /Team/ }));
    fireEvent.click(within(screen.getAllByText("Project Lead")[0].closest(".sugg-i")!).getByRole("button", { name: /Plan a new agent/ }));
    expect(location.hash).toBe("#/onboard");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Plan a new agent");
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Vega" } });
    fireEvent.click(screen.getByRole("button", { name: /Review & activate/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add to project plan" }));
    expect(location.hash).toBe("#/newproject");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    const pd = viewState.get()["page:newproject"].draft as ProjectDraft;
    expect(pd.name).toBe("Listing Scraper");
    expect(pd.planned.map((a) => a.name)).toEqual(["Vega"]);
    expect(pd.lead).toBe("vega");
    expect(o().agents.some((a) => a.id === "vega")).toBe(false);   // not created until the project is approved
    act(() => createProject(pd));
    expect(agent("vega").name).toBe("Vega");
    expect(project("listing-scraper").team.find((m) => m.id === "vega")?.reportsTo).toBe("jay");
  });

  it("cancel discards without creating anything", () => {
    const before = PROJECTS.length;
    go("#/newproject"); render(<App />);
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Discard your changes?" })).getByRole("button", { name: "Discard" }));
    expect(PROJECTS.length).toBe(before);
    expect(o().audit).toHaveLength(0);
  });
});

describe("wizard pop-outs", () => {
  it("both wizards pop out through the window manager, shade the original and keep the draft", () => {
    for (const [route, id] of [["#/onboard", "page:onboard"], ["#/newproject", "page:newproject"]] as const) {
      owners.set({});
      go(route); const r = render(<App />);
      if (id === "page:onboard") { fireEvent.click(screen.getByRole("button", { name: "Implementation Agent template" })); next(); fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Kept" } }); }
      else fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Kept" } });
      fireEvent.click(screen.getAllByTestId(`pop-${id}`)[0]);
      expect(openSpy).toHaveBeenLastCalledWith(expect.stringContaining(`#/pop/${encodeURIComponent(id)}`), expect.any(String), expect.any(String));
      expect(openSpy.mock.lastCall![0]).not.toMatch(/token|secret|key=/i);
      act(() => owners.set((x) => ({ ...x, [id]: { ...x[id], win: "other-window", beat: Date.now() } })));
      expect(screen.getByTestId(`placeholder-${id}`)).toBeInTheDocument();
      // a second pop-out focuses instead of opening another owner
      expect(popOut(id)).toBe("focused");
      // what the pop-out window renders shows the same draft
      r.unmount();
      render(<>{renderView(id)}</>);
      expect(screen.getByDisplayValue("Kept")).toBeInTheDocument();
      cleanup();
      // crash recovery: a dead owner is swept back to the main window
      expect(deadOwners({ [id]: { state: "popped", win: "w", beat: 0, since: 0 } }, 100000, null)).toEqual([id]);
    }
  });

  it("drafts hold no credentials", () => {
    const s = JSON.stringify(viewState.get()) + JSON.stringify(org.get());
    expect(s).not.toMatch(/"(token|password|secret|apiKey|api_key)"\s*:/i);
  });
});
