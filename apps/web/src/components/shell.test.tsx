import { screen } from "@testing-library/react";
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
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/app" }));
vi.mock("@/lib/auth/session", () => ({ useSession: () => ({ signOut: vi.fn() }) }));
vi.mock("./command-palette", () => ({ CommandPalette: () => null }));
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
    expect(screen.getByRole("button", { name: "Sandbox apps, simulated billing" })).toBeInTheDocument();
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
});
