import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { LiveOnly } from "./live-only";
import { StudioHome } from "./studio-home";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const agent = (key: string, name: string, publishedAt: string) => ({
  key,
  name,
  summary: "Reads things.",
  modelProfile: "fast",
  version: 1,
  publishedAt,
  usedBy: [],
});
const pack = (key: string, name: string, added: boolean) => ({
  key,
  name,
  outcome: "Every refund is checked.",
  version: 1,
  publishedAt: "2026-10-04T09:00:00Z",
  steps: 3,
  added,
});
const state = vi.hoisted(() => ({
  workspace: "live",
  role: "owner",
  meError: undefined as Error | undefined,
  agents: [] as unknown[],
  packs: [] as unknown[],
  listings: [] as unknown[],
  earnings: { month: { amountMinor: 0, currency: "USD" }, payouts: [] } as unknown,
  earningsPending: false,
  listingsError: undefined as Error | undefined,
}));

vi.mock("@/lib/queries/me", () => ({
  useMe: () =>
    state.meError
      ? { isPending: false, isError: true, error: state.meError, data: undefined }
      : ok({ workspace: state.workspace, role: state.role }),
  useIsLive: () => !state.meError && state.workspace === "live",
}));
vi.mock("@/lib/queries/studio", () => ({
  useStudioAgents: () => ok(state.agents),
  useStudioPacks: () => ok(state.packs),
}));

vi.mock("@/lib/queries/publishing", () => ({
  useStudioListings: () =>
    state.listingsError
      ? { isPending: false, isError: true, error: state.listingsError, data: undefined, refetch: vi.fn() }
      : ok(state.listings),
  useStudioEarnings: () =>
    state.earningsPending ? { isPending: true, isError: false, data: undefined } : ok(state.earnings),
}));

/** The error panel's Retry resets queries, so it needs a client. */
const Gate = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    <LiveOnly>{children}</LiveOnly>
  </QueryClientProvider>
);

describe("Studio home", () => {
  beforeEach(() => {
    state.workspace = "live";
    state.role = "owner";
    state.meError = undefined;
    state.agents = [];
    state.packs = [];
    state.listings = [];
    state.earnings = { month: { amountMinor: 0, currency: "USD" }, payouts: [] };
    state.earningsPending = false;
    state.listingsError = undefined;
  });

  it("says what the Studio is for and links to new agents and packs", () => {
    renderWithIntl(<StudioHome />);
    expect(screen.getByText("Only your company sees what you build here")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New agent" })).toHaveAttribute("href", "/studio/agents/new");
    expect(screen.getByRole("link", { name: "New pack" })).toHaveAttribute("href", "/studio/packs/new");
    expect(screen.getByText(/No agents yet/)).toBeInTheDocument();
  });

  it("lists the newest few of what the org built as row links, and links to the full lists", () => {
    state.agents = [
      agent("a", "Ledger reader", "2026-10-01T09:00:00Z"),
      agent("b", "Stock watcher", "2026-10-03T09:00:00Z"),
      agent("c", "Refund checker", "2026-10-02T09:00:00Z"),
      agent("d", "Oldest", "2026-09-01T09:00:00Z"),
    ];
    state.packs = [pack("p", "Refund check", true)];
    renderWithIntl(<StudioHome />);
    const rows = screen.getAllByRole("link", { name: /v1$/ });
    expect(rows.map((r) => r.textContent)).toEqual([
      "Stock watcherReads things.v1",
      "Refund checkerReads things.v1",
      "Ledger readerReads things.v1",
      "Refund checkEvery refund is checked.v1",
    ]);
    expect(rows[0]).toHaveAttribute("href", "/studio/agents/b");
    expect(screen.queryByText("Oldest")).toBeNull();
    expect(screen.getByRole("link", { name: "See all 4 agents" })).toHaveAttribute("href", "/studio/agents");
    expect(screen.getByRole("link", { name: "See all 1 pack" })).toHaveAttribute("href", "/studio/packs");
  });

  it("lets the lists shrink to a phone's width, so a long name is cut short instead of widening the page", () => {
    state.agents = [agent("a", "An agent with a very long name that does not fit a phone", "2026-10-01T09:00:00Z")];
    renderWithIntl(<StudioHome />);
    // A grid's automatic column grows to its widest unbreakable line (a truncated name is one); a single
    // minmax(0, 1fr) column cannot, so the names truncate inside it (QA F-11: /studio was 77px too wide at 390).
    const grid = screen.getByRole("heading", { name: "Agents" }).closest("section")!.parentElement!;
    expect(grid).toHaveClass("grid", "grid-cols-1");
  });

  it("says what to do next: an agent first, then a pack, then adding the pack", () => {
    const { unmount } = renderWithIntl(<StudioHome />);
    expect(screen.getByText("Start with an agent, then put it in a pack.")).toBeInTheDocument();
    unmount();
    state.agents = [agent("a", "Ledger reader", "2026-10-01T09:00:00Z")];
    const second = renderWithIntl(<StudioHome />);
    expect(screen.getByText("You have an agent. Next, put it in a pack.")).toBeInTheDocument();
    second.unmount();
    state.packs = [pack("p", "Refund check", false)];
    const third = renderWithIntl(<StudioHome />);
    expect(screen.getByText("Add a pack to your workspace to run it.")).toBeInTheDocument();
    third.unmount();
    state.packs = [pack("p", "Refund check", true)];
    renderWithIntl(<StudioHome />);
    expect(screen.queryByText(/Next|Start with|Add a pack/)).toBeNull();
  });

  it("tells a member that only owners and admins build, and offers no New links or next step", () => {
    state.role = "member";
    renderWithIntl(<StudioHome />);
    expect(screen.getByText("Only owners and admins can build agents and packs.")).toBeInTheDocument();
    expect(screen.queryByText(/Start with an agent/)).toBeNull();
    expect(screen.queryByRole("link", { name: "New agent" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New pack" })).toBeNull();
    // Publishing is for owners and admins only: no Publisher card either.
    expect(screen.queryByText("Publisher")).toBeNull();
    expect(screen.queryByRole("link", { name: /Publisher/ })).toBeNull();
  });

  it("shows a headed notice instead of the Studio in the demo workspace", () => {
    state.workspace = "demo";
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Developer Studio" })).toBeInTheDocument();
    expect(screen.getByText("The Studio is part of the live workspace")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("studio")).toBeNull();
  });

  it("shows the Studio in a live workspace", () => {
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.getByText("studio")).toBeInTheDocument();
    expect(screen.queryByText(/live workspace/)).toBeNull();
  });

  it("shows a failed /v1/me as an error inside the shell, never as a demo", () => {
    state.meError = new ApiError(500, "ERROR", "down");
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This page could not load");
    expect(screen.queryByText(/part of the live workspace/)).toBeNull();
    expect(screen.queryByText("studio")).toBeNull();
  });

  it("keeps the skeleton on a 401, since the client is already signing out", () => {
    state.meError = new ApiError(401, "UNAUTHORIZED", "Sign in");
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/live workspace/)).toBeNull();
    expect(screen.queryByText("studio")).toBeNull();
  });

  it("shows a Publisher card with the listings count and this month's earnings", () => {
    state.listings = [{ id: "l1" }, { id: "l2" }];
    state.earnings = { month: { amountMinor: 4200, currency: "USD" }, payouts: [] };
    renderWithIntl(<StudioHome />);
    expect(screen.getByRole("link", { name: /Publisher/ })).toHaveAttribute("href", "/studio/publisher");
    expect(screen.getByText(/2 listings/)).toHaveTextContent("$42.00");
  });

  it("speaks Japanese", () => {
    state.agents = [
      agent("a", "Ledger reader", "2026-10-01T09:00:00Z"),
      agent("b", "Stock watcher", "2026-10-02T09:00:00Z"),
    ];
    renderWithIntl(<StudioHome />, { locale: "ja" });
    expect(screen.getByRole("link", { name: "新しいエージェント" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "エージェント 2 件をすべて見る" })).toBeInTheDocument();
    expect(screen.getByText("エージェントができました。次はパックに入れましょう。")).toBeInTheDocument();
  });

  it("keeps the Publisher card a skeleton until the earnings have loaded too", () => {
    state.listings = [{ id: "l1" }];
    state.earningsPending = true;
    renderWithIntl(<StudioHome />);
    expect(screen.queryByText(/1 listing/)).toBeNull();
  });

  it("shows a failed listings read inside the Publisher card, with a retry, and keeps the Studio", () => {
    state.listingsError = new ApiError(500, "BOOM", "Listings are down.");
    renderWithIntl(<StudioHome />);
    expect(screen.getByText("Listings are down.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New agent" })).toBeInTheDocument();
  });
});
