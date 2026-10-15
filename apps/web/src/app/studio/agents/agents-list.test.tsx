import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { AgentsList } from "./agents-list";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const AGENTS = [
  {
    key: "org-a1--ledger-reader",
    name: "Ledger reader",
    summary: "Reads orders and charges.",
    modelProfile: "reasoning",
    version: 3,
    publishedAt: "2026-10-14T09:00:00Z",
    usedBy: ["Refund check", "Shared pack"],
  },
  {
    key: "org-a1--stock-watcher",
    name: "Stock watcher",
    summary: "Watches stock levels.",
    modelProfile: "fast",
    version: 1,
    publishedAt: "2026-10-14T09:00:00Z",
    usedBy: [],
  },
];
const PACKS = [
  {
    key: "org-a1--refund-check",
    name: "Refund check",
    outcome: "Every refund is checked.",
    version: 2,
    publishedAt: "2026-10-14T09:00:00Z",
    steps: 6,
    added: true,
  },
];
const mocks = vi.hoisted(() => ({ agents: [] as unknown[], packs: [] as unknown[], role: "owner" }));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ok({ orgId: "org_a1", role: mocks.role }) }));
vi.mock("@/lib/queries/studio", () => ({
  useStudioAgents: () => ok(mocks.agents),
  useStudioPacks: () => ok(mocks.packs),
}));

describe("AgentsList", () => {
  beforeEach(() => {
    mocks.agents = AGENTS;
    mocks.packs = PACKS;
    mocks.role = "owner";
  });

  it("lists the org's agents with their model and a short version", () => {
    renderWithIntl(<AgentsList />);
    expect(screen.getByRole("link", { name: "Ledger reader" })).toHaveAttribute(
      "href",
      "/studio/agents/org-a1--ledger-reader",
    );
    expect(screen.getByText("Reasoning model")).toBeInTheDocument();
    expect(screen.getByText("Fast model")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Version" })).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.queryByText("Version 3")).toBeNull();
    expect(screen.getByText("Not used by a pack yet")).toBeInTheDocument();
  });

  it("links a pack that uses the agent when it is one of the org's own; other names stay plain", () => {
    renderWithIntl(<AgentsList />);
    expect(screen.getByRole("link", { name: "Refund check" })).toHaveAttribute(
      "href",
      "/studio/packs/org-a1--refund-check",
    );
    expect(screen.queryByRole("link", { name: "Shared pack" })).toBeNull();
    expect(screen.getByText("Shared pack")).toBeInTheDocument();
  });

  it("makes the whole row the agent's link, and stacks rows as cards on narrow screens", () => {
    renderWithIntl(<AgentsList />);
    const name = screen.getByRole("link", { name: "Stock watcher" });
    expect(name.className).toContain("after:inset-0");
    const row = name.closest("tr");
    expect(row?.className).toContain("relative");
    expect(row?.className).toMatch(/\bgrid\b/);
    expect(row?.className).toContain("sm:table-row");
  });

  it("offers a first agent to builders, and tells a member who can make one", () => {
    mocks.agents = [];
    const { unmount } = renderWithIntl(<AgentsList />);
    expect(screen.getByRole("link", { name: "New agent" })).toHaveAttribute("href", "/studio/agents/new");
    unmount();
    mocks.role = "member";
    renderWithIntl(<AgentsList />);
    expect(screen.queryByRole("link", { name: "New agent" })).toBeNull();
    expect(screen.getByText("No agents yet. An owner or admin can build one.")).toBeInTheDocument();
  });

  it("speaks Japanese", () => {
    renderWithIntl(<AgentsList />, { locale: "ja" });
    expect(screen.getByRole("columnheader", { name: "使用しているパック" })).toBeInTheDocument();
    expect(screen.getByText("まだパックで使われていません")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
  });
});
