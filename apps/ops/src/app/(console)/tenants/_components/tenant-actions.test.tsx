import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { TenantDetail } from "@/lib/api/gen/types.gen";
import { TenantActions } from "./tenant-actions";

const canWrite = vi.hoisted(() => ({ value: true }));
const mutations = vi.hoisted(() => ({
  suspend: vi.fn(),
  reactivate: vi.fn(),
  setPlan: vi.fn(),
  setCap: vi.fn(),
}));

const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite.value, useOpsWorkspace: () => workspace.value }));
vi.mock("@/lib/queries/tenants", () => ({
  useSuspendTenant: () => ({ mutateAsync: mutations.suspend }),
  useReactivateTenant: () => ({ mutateAsync: mutations.reactivate }),
  useSetTenantPlan: () => ({ mutateAsync: mutations.setPlan }),
  useSetTenantSpendCap: () => ({ mutateAsync: mutations.setCap }),
}));

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const tenant = (over: Partial<TenantDetail> = {}): TenantDetail => ({
  id: "org_hp01",
  name: "Harbor & Pine Supply Co.",
  short: "Harbor & Pine",
  plan: "Pro",
  status: "active",
  region: "us-central1",
  country: "US",
  ownerEmail: "ops@harborandpine.example",
  seats: 5,
  members: 2,
  createdAt: "2026-03-02T17:20:00Z",
  monthlyCap: usd(25000),
  monthSpent: usd(6194),
  runs30d: 46,
  successRate: 0.91,
  openHumanTasks: 3,
  packsInstalled: 4,
  connectors: 6,
  health: "healthy",
  notes: "",
  membersList: [],
  installedPacks: [],
  connectorsList: [],
  recentRuns: [],
  usageByDay: [],
  simulated: true,
  ...over,
});

const renderActions = (t: TenantDetail) =>
  render(
    <UiProviders>
      <TenantActions tenant={t} />
    </UiProviders>,
  );

beforeEach(() => {
  canWrite.value = true;
  workspace.value = "demo";
  Object.values(mutations).forEach((m) => m.mockReset());
});

describe("TenantActions", () => {
  it("disables every trigger for the support role", () => {
    canWrite.value = false;
    renderActions(tenant());
    for (const name of ["Change plan", "Set spend cap", "Suspend tenant"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("hides Change plan in the live workspace and keeps the actions that work on real orgs", () => {
    workspace.value = "live";
    renderActions(tenant({ simulated: false }));
    expect(screen.queryByRole("button", { name: "Change plan" })).toBeNull();
    expect(screen.getByRole("button", { name: "Set spend cap" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Suspend tenant" })).toBeEnabled();
  });

  it("says in the live suspend confirm that runs already in progress keep going", async () => {
    const user = userEvent.setup();
    const inProgress = "Runs already in progress keep going until they reach a step this company has to act on.";
    workspace.value = "live";
    const { unmount } = renderActions(tenant({ simulated: false }));
    await user.click(screen.getByRole("button", { name: "Suspend tenant" }));
    expect(within(await screen.findByRole("alertdialog")).getByText(new RegExp(inProgress))).toBeInTheDocument();
    unmount();
    workspace.value = "demo";
    renderActions(tenant());
    await user.click(screen.getByRole("button", { name: "Suspend tenant" }));
    expect(within(await screen.findByRole("alertdialog")).queryByText(new RegExp(inProgress))).not.toBeInTheDocument();
  });

  it("hides Suspend for a churned tenant", () => {
    renderActions(tenant({ status: "churned" }));
    expect(screen.queryByRole("button", { name: "Suspend tenant" })).not.toBeInTheDocument();
  });

  it("offers Reactivate instead of Suspend for a suspended tenant", () => {
    renderActions(tenant({ status: "suspended" }));
    expect(screen.getByRole("button", { name: "Reactivate tenant" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Suspend tenant" })).not.toBeInTheDocument();
  });

  it("keeps the Change plan confirm disabled while the plan is unchanged", async () => {
    const user = userEvent.setup();
    renderActions(tenant());
    await user.click(screen.getByRole("button", { name: "Change plan" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Upgrade requested");
    expect(within(dialog).getByRole("button", { name: "Change plan" })).toBeDisabled();
  });

  it("keeps the spend cap confirm disabled for an unchanged or malformed amount", async () => {
    const user = userEvent.setup();
    renderActions(tenant());
    await user.click(screen.getByRole("button", { name: "Set spend cap" }));
    const dialog = await screen.findByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Set spend cap" });
    expect(within(dialog).getByLabelText("Monthly cap (USD)")).toHaveValue("250.00");
    expect(confirm).toBeDisabled();
    await user.clear(within(dialog).getByLabelText("Monthly cap (USD)"));
    await user.type(within(dialog).getByLabelText("Monthly cap (USD)"), "1e3");
    expect(confirm).toBeDisabled();
  });
});
