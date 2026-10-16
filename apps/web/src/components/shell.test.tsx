import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { AppShell, type ShellMode } from "./shell";
import { TourContext } from "./tour/tour-context";

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
  studio: { agent: undefined as string | undefined, pack: undefined as string | undefined },
  packs: [] as { slug: string; installed: boolean }[],
}));

// The workspace menu's language items refresh the router after a choice; the menu must open without one.
vi.mock("next/navigation", () => ({ usePathname: () => data.path, useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/auth/session", () => ({ useSession: () => ({ signOut: vi.fn() }) }));
// The palette itself is tested on its own; here it only reports the pages AppShell hands it.
vi.mock("./command-palette", () => ({
  CommandPalette: ({
    pages,
    actions = [],
  }: {
    pages: { href: string }[];
    actions?: { id: string; label: string; run: (opener: Element | null) => void }[];
  }) => (
    <div data-testid="palette-pages" data-hrefs={pages.map((p) => p.href).join(" ")}>
      {actions.map((a) => (
        <button key={a.id} type="button" data-testid={`palette-action-${a.id}`} onClick={() => a.run(null)}>
          {a.label}
        </button>
      ))}
    </div>
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
  usePacks: () => ok(data.packs),
  usePackName: () => undefined,
  useAgentName: () => undefined,
}));
vi.mock("@/lib/queries/studio", () => ({
  useStudioAgent: (key?: string) => ({
    data: key && data.studio.agent ? { draft: { name: data.studio.agent } } : undefined,
  }),
  useStudioPack: (key?: string) => ({
    data: key && data.studio.pack ? { draft: { name: data.studio.pack } } : undefined,
  }),
}));
vi.mock("@/lib/queries/publishing", () => ({
  useStudioListing: (id?: string) => ({ data: id ? { name: "Refund check" } : undefined }),
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
    data.studio = { agent: undefined, pack: undefined };
    data.packs = [];
  });

  it("names the signed-in user's own workspace, plan and role", () => {
    renderWithIntl(<AppShell>page</AppShell>);
    expect(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Trial").length).toBeGreaterThan(0);
    expect(screen.getByText("Ana Reyes")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.queryByText(/Harbor/)).not.toBeInTheDocument();
  });

  it("labels a live workspace's sandbox apps and billing in the sidebar and, below lg, in a strip under the top bar", () => {
    renderWithIntl(<AppShell>page</AppShell>);
    const badges = screen.getAllByRole("button", { name: "Simulated data, simulated billing" });
    expect(badges).toHaveLength(1);
    expect(screen.getByRole("complementary")).toContainElement(badges[0]);
    expect(screen.getByRole("banner")).not.toContainElement(badges[0]);
    expect(screen.queryByText(/Demo workspace/)).not.toBeInTheDocument();
    // The sidebar is hidden below lg: the strip keeps the label on screen, with the full sentence as its title.
    const strip = screen.getAllByText("Simulated data, simulated billing").find((el) => el.tagName === "DIV");
    expect(strip).toHaveClass("lg:hidden");
    expect(strip).toHaveAttribute("title", expect.stringContaining("no money moves"));
    expect(screen.getByRole("complementary")).not.toContainElement(strip as HTMLElement);
  });

  it("gives the sidebar and the drawer's nav groups different ids", async () => {
    renderWithIntl(<AppShell>page</AppShell>);
    await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const lists = screen.getAllByRole("list", { name: "Work", hidden: true });
    expect(lists).toHaveLength(2);
    const ids = lists.map((l) => l.getAttribute("aria-labelledby"));
    expect(new Set(ids).size).toBe(2);
    for (const id of ids) expect(document.querySelectorAll(`[id="${id}"]`)).toHaveLength(1);
  });

  it("groups the business sidebar with labels, the other roles' areas last", () => {
    renderWithIntl(<AppShell>page</AppShell>);
    const nav = within(screen.getByRole("complementary")).getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("list", { name: "Work" })).toContainElement(
      within(nav).getByRole("link", { name: "Runs" }),
    );
    expect(within(nav).getByRole("list", { name: "Setup" })).toContainElement(
      within(nav).getByRole("link", { name: "Connections" }),
    );
    expect(within(nav).getByRole("list", { name: "Account" })).toContainElement(
      within(nav).getByRole("link", { name: "Settings" }),
    );
    const other = within(nav).getByRole("list", { name: "Other areas" });
    expect(within(other).getByRole("link", { name: "Reviewer portal" })).toHaveAttribute("href", "/work");
    expect(within(other).getByRole("link", { name: "Developer Studio" })).toHaveAttribute("href", "/studio");
  });

  it("names a top-level page in the top bar only until the page brings its own heading", () => {
    data.path = "/app/approvals";
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    const crumbs = () => screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(crumbs()).toHaveTextContent("Approvals");
    expect(crumbs()).toHaveClass("page-crumb"); // hidden by the shell once <main> holds an h1
    unmount();
    data.path = "/app/runs/run_2012";
    renderWithIntl(<AppShell>page</AppShell>);
    expect(crumbs()).toHaveTextContent("Runsrun_2012");
    expect(crumbs()).not.toHaveClass("page-crumb"); // a trail stays beside the page's heading
  });

  it("calls an added pack's install page its settings, not Add, in a live workspace", () => {
    const trail = () =>
      within(screen.getByRole("navigation", { name: "Breadcrumb" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent);
    data.path = "/app/marketplace/recon/install";
    data.packs = [{ slug: "recon", installed: false }];
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    expect(trail().at(-1)).toBe("Add");
    unmount();
    data.packs = [{ slug: "recon", installed: true }];
    const live = renderWithIntl(<AppShell>page</AppShell>);
    expect(trail().at(-1)).toBe("Settings");
    live.unmount();
    // The demo keeps the add flow for an added pack, so its crumb stays.
    data.me = ok({ ...LIVE_ME, workspace: "demo" });
    renderWithIntl(<AppShell>page</AppShell>);
    expect(trail().at(-1)).toBe("Add");
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
    expect(hrefs).toEqual(["/studio", "/studio/agents", "/studio/packs", "/studio/publisher"]);
    expect(screen.getAllByRole("link", { name: "Publisher" })[0]).toHaveAttribute("href", "/studio/publisher");
  });

  it("lists Publisher in the Studio for owners and admins only", () => {
    data.me = ok({ ...LIVE_ME, role: "member" });
    renderWithIntl(<AppShell mode="studio">page</AppShell>);
    expect(screen.queryByRole("link", { name: "Publisher" })).toBeNull();
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

  it("reads a saved Studio record by its name once it has loaded", () => {
    data.studio.pack = "Invoice checks";
    data.path = "/studio/packs/acme--invoices";
    renderWithIntl(<AppShell mode="studio">page</AppShell>);
    expect(
      within(screen.getByRole("navigation", { name: "Breadcrumb" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Workflow Packs", "Invoice checks"]);
  });

  it("reads a Publisher listing by its name, not its id", () => {
    data.path = "/studio/publisher/lst_123";
    renderWithIntl(<AppShell mode="studio">page</AppShell>);
    expect(
      within(screen.getByRole("navigation", { name: "Breadcrumb" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Publisher", "Refund check"]);
  });

  it("names the reviewer portal's pages in the top bar, which the page's own heading does not hide", () => {
    data.path = "/work/earnings";
    const { unmount } = renderWithIntl(<AppShell mode="work">page</AppShell>);
    const crumbs = () => screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(crumbs()).toHaveTextContent("Earnings");
    expect(crumbs()).not.toHaveClass("page-crumb");
    unmount();
    data.path = "/work/tasks/ht_run_2012_review_1";
    renderWithIntl(<AppShell mode="work">page</AppShell>);
    expect(crumbs()).toHaveTextContent("Available tasksTask");
    expect(crumbs()).not.toHaveTextContent("ht_run");
  });

  it("offers the Developer Studio in the workspace menu of a live workspace only", async () => {
    const { unmount } = renderWithIntl(<AppShell>page</AppShell>);
    await userEvent.click(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0]);
    expect(await screen.findByRole("menuitem", { name: /Developer Studio/ })).toHaveAttribute("href", "/studio");
    // The menu is grouped: where to switch to, the language, then the account.
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("group", { name: "Switch to" })).toContainElement(
      within(menu).getByRole("menuitem", { name: /Reviewer portal/ }),
    );
    expect(within(menu).getByRole("group", { name: "Language" })).toBeInTheDocument();
    const account = within(menu).getByRole("group", { name: "Account" });
    expect(account).toHaveTextContent("Signed in as Ana Reyes");
    expect(within(account).getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
    unmount();
    data.me = ok({ ...LIVE_ME, workspace: "demo" });
    renderWithIntl(<AppShell>page</AppShell>);
    await userEvent.click(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0]);
    expect(await screen.findByRole("menuitem", { name: /Reviewer portal/ })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Developer Studio/ })).toBeNull();
  });

  describe("the tour", () => {
    const replay = vi.fn();
    const withTour = (mode: ShellMode = "business") =>
      renderWithIntl(
        <TourContext value={{ start: () => false, replay, pending: null, clearPending: vi.fn(), visible: false }}>
          <AppShell mode={mode}>page</AppShell>
        </TourContext>,
      );
    beforeEach(() => replay.mockReset());

    it("replays the welcome tour from the workspace menu, on its overview, back to the menu", async () => {
      data.path = "/app/marketplace";
      withTour();
      const trigger = screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0];
      await userEvent.click(trigger);
      await userEvent.click(await screen.findByRole("menuitem", { name: "Take the tour" }));
      expect(replay).toHaveBeenCalledWith("welcome", { href: "/app", opener: trigger });
    });

    it.each([["/app/runs/run_1042"], ["/app/runs/run_1042/evidence"]])(
      "replays the run tour on the run page from %s",
      async (path) => {
        data.path = path;
        withTour();
        await userEvent.click(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0]);
        await userEvent.click(await screen.findByRole("menuitem", { name: "Take the tour" }));
        expect(replay).toHaveBeenCalledWith("run", expect.objectContaining({ href: "/app/runs/run_1042" }));
      },
    );

    it("replays the Studio tour in the Studio", async () => {
      data.path = "/studio/packs";
      withTour("studio");
      await userEvent.click(screen.getAllByRole("button", { name: "Ana's workspace, switch workspace" })[0]);
      await userEvent.click(await screen.findByRole("menuitem", { name: "Take the tour" }));
      expect(replay).toHaveBeenCalledWith("studio", expect.objectContaining({ href: "/studio" }));
    });

    it("offers no tour in the reviewer portal", async () => {
      data.path = "/work";
      withTour("work");
      expect(screen.queryByTestId("palette-action-tour")).not.toBeInTheDocument();
      await userEvent.click(screen.getAllByRole("button", { name: /switch workspace/ })[0]);
      await screen.findByRole("menuitem", { name: "Sign out" });
      expect(screen.queryByRole("menuitem", { name: "Take the tour" })).not.toBeInTheDocument();
    });

    it("hands the palette a Take the tour action for the current area", async () => {
      data.path = "/app";
      withTour();
      await userEvent.click(screen.getByTestId("palette-action-tour"));
      expect(replay).toHaveBeenCalledWith("welcome", { href: "/app", opener: null });
    });
  });
});
