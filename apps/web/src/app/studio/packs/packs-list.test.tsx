import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PacksList } from "./packs-list";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
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
  {
    key: "org-a1--stock-alert",
    name: "Stock alert",
    outcome: "Low stock gets flagged.",
    version: 1,
    publishedAt: "2026-10-14T09:00:00Z",
    steps: 4,
    added: false,
  },
];
const mocks = vi.hoisted(() => ({ packs: [] as unknown[], role: "owner" }));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ok({ orgId: "org_a1", role: mocks.role }) }));
vi.mock("@/lib/queries/studio", () => ({ useStudioPacks: () => ok(mocks.packs) }));

describe("PacksList", () => {
  beforeEach(() => {
    mocks.packs = PACKS;
    mocks.role = "owner";
  });

  it("lists the org's packs with their version and whether they are added", () => {
    renderWithIntl(<PacksList />);
    expect(screen.getByRole("link", { name: "Refund check" })).toHaveAttribute(
      "href",
      "/studio/packs/org-a1--refund-check",
    );
    expect(screen.getByText("Added to your workspace")).toBeInTheDocument();
    expect(screen.getByText("Not added yet")).toBeInTheDocument();
    expect(screen.getByText("6 steps")).toBeInTheDocument();
    // The column header says "Version" once; the cell is the short form.
    expect(screen.getByRole("columnheader", { name: "Version" })).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.queryByText("Version 2")).toBeNull();
  });

  it("offers to add a pack that is not in the workspace yet, on its marketplace page", () => {
    renderWithIntl(<PacksList />);
    expect(screen.getAllByRole("link", { name: "Add to workspace" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Add to workspace" })).toHaveAttribute(
      "href",
      "/app/marketplace/org-a1--stock-alert",
    );
  });

  it("offers builders a Duplicate link on each row that opens a copy, and members none", () => {
    const { unmount } = renderWithIntl(<PacksList />);
    const links = screen.getAllByRole("link", { name: /^Duplicate / });
    expect(links.map((l) => l.getAttribute("aria-label"))).toEqual(["Duplicate Refund check", "Duplicate Stock alert"]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/studio/packs/new?from=org-a1--refund-check",
      "/studio/packs/new?from=org-a1--stock-alert",
    ]);
    unmount();
    mocks.role = "member";
    renderWithIntl(<PacksList />);
    expect(screen.queryByRole("link", { name: /^Duplicate / })).toBeNull();
  });

  it("makes the whole row the pack's link, and stacks rows as cards on narrow screens", () => {
    renderWithIntl(<PacksList />);
    const name = screen.getByRole("link", { name: "Refund check" });
    expect(name.className).toContain("after:inset-0");
    const row = name.closest("tr");
    expect(row?.className).toContain("relative");
    expect(row?.className).toMatch(/\bgrid\b/);
    expect(row?.className).toContain("sm:table-row");
  });

  it("offers a first pack to builders, and tells a member who can make one", () => {
    mocks.packs = [];
    const { unmount } = renderWithIntl(<PacksList />);
    expect(screen.getByRole("link", { name: "New pack" })).toHaveAttribute("href", "/studio/packs/new");
    unmount();
    mocks.role = "member";
    renderWithIntl(<PacksList />);
    expect(screen.queryByRole("link", { name: "New pack" })).toBeNull();
    expect(screen.getByText("No packs yet. An owner or admin can build one.")).toBeInTheDocument();
  });
});
