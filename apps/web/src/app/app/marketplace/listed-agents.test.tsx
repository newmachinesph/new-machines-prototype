import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Agent } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { ListedAgents } from "./listed-agents";

const role = vi.hoisted(() => ({ canBuild: true }));
vi.mock("@/app/studio/can-build", () => ({ useCanBuild: () => role.canBuild }));

const agent = (over: Partial<Agent> & Pick<Agent, "id" | "name">): Agent => ({
  version: "1.0.0",
  publisher: "Harbor Cafe",
  summary: `${over.name} summary`,
  capabilities: [],
  regions: ["asia-south1"],
  certified: false,
  skills: [],
  tools: [],
  usedBy: [],
  source: "definition",
  listing: {
    listingId: "lst_1",
    publisher: "Harbor Cafe",
    fee: { amountMinor: 30, currency: "USD" },
    feeUnit: "call",
    version: 2,
  },
  ...over,
});

describe("ListedAgents", () => {
  beforeEach(() => {
    role.canBuild = true;
  });

  it("offers the Studio only to those who can build", () => {
    role.canBuild = false;
    renderWithIntl(<ListedAgents agents={[agent({ id: "tax-agent", name: "Tax Agent" })]} />);
    expect(screen.queryByRole("link", { name: "Use it in the Studio" })).toBeNull();
  });

  it("says so when no agent is listed", () => {
    renderWithIntl(<ListedAgents agents={[]} />);
    expect(screen.getByText("No agents are listed by other publishers yet.")).toBeInTheDocument();
  });

  it("shows each row with publisher, per-call fee and a link to the Studio", () => {
    renderWithIntl(<ListedAgents agents={[agent({ id: "tax-agent", name: "Tax Agent" })]} />);
    const row = screen.getByRole("link", { name: "Tax Agent" }).closest("li")!;
    expect(screen.getByRole("link", { name: "Tax Agent" })).toHaveAttribute("href", "/app/agents/tax-agent");
    expect(within(row).getByText("By Harbor Cafe")).toBeInTheDocument();
    expect(within(row).getByText("$0.30 per call")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Use it in the Studio" })).toHaveAttribute("href", "/studio/packs");
  });
});
