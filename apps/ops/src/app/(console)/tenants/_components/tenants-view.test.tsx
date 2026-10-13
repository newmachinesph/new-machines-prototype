import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { TenantsView } from "./tenants-view";

const state = vi.hoisted(() => ({
  workspace: "demo" as "demo" | "live",
  action: null as string | null,
  setAction: vi.fn(),
}));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({ withDefault: () => ({}) }),
  useQueryState: (key: string) =>
    key === "status" ? ["all", vi.fn()] : key === "q" ? ["", vi.fn()] : [state.action, state.setAction],
}));
vi.mock("@/lib/queries/ops", () => ({
  useCanWrite: () => true,
  useMe: () => ({ isSuccess: true }),
  useOpsWorkspace: () => state.workspace,
}));
vi.mock("@/lib/queries/tenants", () => ({
  useTenants: () => ({ isPending: false, isError: false, data: [] }),
}));
vi.mock("./new-tenant-dialog", () => ({
  NewTenantDialog: ({ open }: { open: boolean }) => (open ? <div data-testid="new-tenant-dialog" /> : null),
}));

const renderView = () =>
  render(
    <UiProviders>
      <TenantsView />
    </UiProviders>,
  );

describe("TenantsView", () => {
  beforeEach(() => {
    state.workspace = "demo";
    state.action = null;
    state.setAction.mockClear();
  });

  it("offers New tenant in the demo", () => {
    renderView();
    expect(screen.getByRole("button", { name: "New tenant" })).toBeEnabled();
    expect(screen.getByText("No tenants yet. Create one with New tenant.")).toBeInTheDocument();
  });

  it("hides New tenant in the live workspace, where orgs are created at sign-up", () => {
    state.workspace = "live";
    state.action = "new";
    renderView();
    expect(screen.queryByRole("button", { name: "New tenant" })).toBeNull();
    expect(screen.queryByTestId("new-tenant-dialog")).toBeNull();
    expect(screen.getByText("No tenants yet. Orgs appear here when people sign up.")).toBeInTheDocument();
    expect(state.setAction).toHaveBeenCalledWith(null);
  });
});
