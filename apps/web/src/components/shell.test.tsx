import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { AppShell } from "./shell";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
type MeState = { isPending: boolean; isError: boolean; data?: Record<string, string> };
const LIVE_ME = {
  userId: "u1",
  orgId: "org_new",
  orgName: "Ana's workspace",
  role: "owner",
  name: "Ana Reyes",
  workspace: "live",
};
const data = vi.hoisted(() => ({
  me: { isPending: false, isError: false, data: {} } as MeState,
  plan: "Trial",
  path: "/app",
}));

// The workspace menu's language items refresh the router after a choice; the menu must open without one.
vi.mock("next/navigation", () => ({ usePathname: () => data.path, useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/auth/session", () => ({ useSession: () => ({ signOut: vi.fn() }) }));
// The palette itself is tested on its own; here it only reports the pages AppShell hands it.
vi.mock("./command-palette", () => ({
  CommandPalette: ({ pages }: { pages: { href: string }[] }) => (
    <div data-testid="palette-pages" data-hrefs={pages.map((p) => p.href).join(" ")} />
  ),
}));
vi.mock("./base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./base")>()),
  useToast: () => vi.fn(),
}));
vi.mock("@/lib/queries/me", () => ({
  useMe: () => data.me,
  useIsDemo: () => data.me.data?.workspace === "demo",
  useIsLive: () => data.me.data?.workspace === "live",
}));
vi.mock("@/lib/queries/org", () => ({ useOrg: () => ok({ plan: data.plan }) }));
vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () => ok([]),
  usePackName: () => undefined,
  useAgentName: () => undefined,
}));
vi.mock("@/lib/queries/tasks", () => ({ useEligibleTasks: () => ok([]) }));
vi.mock("@/lib/queries/workspace", () => ({ useApprovals: () => ok([]), useMemory: () => ok([]) }));

describe("AppShell", () => {
  beforeEach(() => {
    // jsdom has no matchMedia; the drawer listens for the wide layout.
    window.matchMedia = vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as never;
    data.me = ok({ ...LIVE_ME });
    data.plan = "Trial";
    data.path = "/app";
  });

  it("names the signed-in user's own workspace, plan and role", () => {
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Trial").length).toBeGreaterThan(0);
    expect(screen.getByText("Ana Reyes")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.queryByText(/Harbor/)).not.toBeInTheDocument();
  });

  it("labels a live workspace's sandbox apps and billing, not a demo", () => {
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getByRole("button", { name: "Simulated data, simulated billing" })).toBeInTheDocument();
    expect(screen.queryByText(/Demo workspace/)).not.toBeInTheDocument();
  });

  it("keeps the demo workspace's name and label", () => {
    data.me = ok({
      userId: "demo",
      orgId: "org_hp01",
      orgName: "Harbor & Pine Supply Co.",
      role: "owner",
      workspace: "demo",
    });
    data.plan = "Pro";
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByText("Harbor & Pine Supply Co.").length).toBeGreaterThan(0);
    expect(screen.getByText("Demo operator")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Demo workspace: synthetic data, simulated billing" }),
    ).toBeInTheDocument();
  });

  it("names a live user without a name by their email, then as You, never as the demo operator", () => {
    data.me = ok({ ...LIVE_ME, name: "", email: "ana@example.com" });
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getByText("ana@example.com")).toBeInTheDocument();
    unmount();
    data.me = ok({ ...LIVE_ME, name: "", email: "" });
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.queryByText("Demo operator")).not.toBeInTheDocument();
  });

  it("names the signed-in reviewer in a live reviewer portal, and keeps the demo reviewer in the demo", () => {
    data.me = ok({ ...LIVE_ME, role: "owner" }); // an owner reviewing works as a reviewer here
    const { unmount } = renderWithIntl(<AppShell mode="work">page</AppShell>);
    expect(screen.getByText("Ana Reyes")).toBeInTheDocument();
    expect(screen.getByText("Reviewer")).toBeInTheDocument();
    expect(screen.queryByText("Reviewer 204")).not.toBeInTheDocument();
    unmount();
    data.me = ok({ userId: "demo", orgId: "org_hp01", orgName: "Harbor", role: "owner", workspace: "demo" });
    renderWithIntl(<AppShell mode="work">page</AppShell>);
    expect(screen.getAllByText("Reviewer 204").length).toBeGreaterThan(0);
  });

  it("lists Reviewers only in a live workspace", () => {
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByRole("link", { name: "Reviewers" })[0]).toHaveAttribute("href", "/app/reviewers");
    unmount();
    data.me = ok({ ...LIVE_ME, workspace: "demo" });
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.queryByRole("link", { name: "Reviewers" })).toBeNull();
  });

  it("lists the Developer Studio in the business sidebar only in a live workspace", () => {
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByRole("link", { name: "Developer Studio" })[0]).toHaveAttribute("href", "/studio");
    unmount();
    data.me = ok({ ...LIVE_ME, workspace: "demo" });
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.queryByRole("link", { name: "Developer Studio" })).toBeNull();
  });

  it("offers Reviewers in the command palette only in a live workspace", () => {
    const hrefs = () => (screen.getByTestId("palette-pages").dataset.hrefs ?? "").split(" ");
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    expect(hrefs()).toContain("/app/reviewers");
    expect(hrefs()).toContain("/app/settings");
    unmount();
    data.me = ok({ ...LIVE_ME, workspace: "demo" });
    renderWithIntl(<AppShell>page</AppShell>);
    expect(hrefs()).not.toContain("/app/reviewers");
    expect(hrefs()).toContain("/app/settings");
  });

  it("gives the workspace control a name while /v1/me loads", () => {
    data.me = { isPending: true, isError: false };
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByRole("button", { name: "Loading workspace, switch workspace" }).length).toBeGreaterThan(0);
  });

  it("says the workspace is unavailable when /v1/me fails", () => {
    data.me = { isPending: false, isError: true };
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByText("Workspace unavailable").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Workspace unavailable, switch workspace" }).length).toBeGreaterThan(
      0,
    );
  });

  it("shows the Studio's navigation in studio mode, and links back to the business workspace", () => {
    renderWithIntl(<AppShell mode="studio">page</AppShell>);
    expect(screen.getAllByRole("link", { name: "Agents" })[0]).toHaveAttribute("href", "/studio/agents");
    expect(screen.getAllByRole("link", { name: "Workflow Packs" })[0]).toHaveAttribute("href", "/studio/packs");
    expect(screen.getAllByRole("link", { name: "Business workspace" })[0]).toHaveAttribute("href", "/app");
    expect(screen.queryByRole("link", { name: "Approvals" })).toBeNull();
    const hrefs = (screen.getByTestId("palette-pages").dataset.hrefs ?? "").split(" ");
    expect(hrefs).toEqual(["/studio", "/studio/agents", "/studio/packs"]);
  });

  it("reads a new Studio record as New, and a saved one by the name part of its key", () => {
    const crumbs = () =>
      within(screen.getByRole("navigation", { name: "Breadcrumb" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent);
    data.path = "/studio/packs/new";
    const { unmount } = renderWithIntl(<AppShell mode="studio">page</AppShell>);
    expect(crumbs()).toEqual(["Workflow Packs", "New"]);
    expect(
      within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Workflow Packs" }),
    ).toHaveAttribute("href", "/studio/packs");
    unmount();
    data.path = "/studio/packs/acme--invoices";
    renderWithIntl(<AppShell mode="studio">page</AppShell>);
    expect(crumbs()).toEqual(["Workflow Packs", "invoices"]);
  });

  it("offers the Developer Studio in the workspace menu of a live workspace only", async () => {
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    await userEvent.click(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0]);
    expect(await screen.findByRole("menuitem", { name: /Developer Studio/ })).toHaveAttribute("href", "/studio");
    unmount();
    data.me = ok({ ...LIVE_ME, workspace: "demo" });
    renderWithIntl(<AppShell>page</AppShell>);
    await userEvent.click(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0]);
    expect(await screen.findByRole("menuitem", { name: /Reviewer portal/ })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Developer Studio/ })).toBeNull();
  });
});
