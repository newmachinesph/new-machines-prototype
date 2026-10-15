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
    expect(screen.getByText("Version 2")).toBeInTheDocument();
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
