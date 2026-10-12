import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { MarketplaceView } from "./marketplace-view";

const state = vi.hoisted(() => ({
  canWrite: true,
  roleKnown: true,
  action: "new" as string | null,
  setAction: vi.fn(),
}));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({}),
  useQueryState: (key: string) => (key === "action" ? [state.action, state.setAction] : [null, vi.fn()]),
}));
vi.mock("@/lib/queries/ops", () => ({
  useCanWrite: () => state.canWrite,
  useMe: () => ({ isSuccess: state.roleKnown }),
}));
vi.mock("@/lib/queries/marketplace", () => ({
  usePacks: () => ({ isPending: false, isError: false, data: [] }),
}));
vi.mock("./new-pack-dialog", () => ({ NewPackDialog: () => <div data-testid="new-pack-dialog" /> }));

const renderView = () =>
  render(
    <UiProviders>
      <MarketplaceView />
    </UiProviders>,
  );

describe("MarketplaceView ?action=new", () => {
  beforeEach(() => {
    state.canWrite = true;
    state.roleKnown = true;
    state.action = "new";
    state.setAction.mockClear();
  });

  it("mounts the New pack dialog for an operator", () => {
    renderView();
    expect(screen.getByTestId("new-pack-dialog")).toBeInTheDocument();
    expect(state.setAction).not.toHaveBeenCalled();
  });

  it("does not mount the dialog for support and clears the parameter", () => {
    state.canWrite = false;
    renderView();
    expect(screen.queryByTestId("new-pack-dialog")).toBeNull();
    expect(state.setAction).toHaveBeenCalledWith(null);
    expect(screen.getByRole("button", { name: "New pack" })).toBeDisabled();
  });

  it("leaves the parameter alone until the role is known", () => {
    state.canWrite = false;
    state.roleKnown = false;
    renderView();
    expect(state.setAction).not.toHaveBeenCalled();
  });
});
