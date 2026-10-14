import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { InstallPage } from "./install-page";

vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
// The page decides the mode; the form only reports what it was told.
vi.mock("./install-review", () => ({
  InstallReview: ({ settings }: { settings: boolean }) => <p>{settings ? "settings mode" : "add mode"}</p>,
}));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const state = vi.hoisted(() => ({ installed: true, live: true }));
vi.mock("@/lib/queries/me", () => ({ useIsLive: () => state.live }));
vi.mock("@/lib/queries/catalog", () => ({
  usePack: () => ok({ slug: "order-payment-reconciliation", name: "Order Recon", installed: state.installed }),
  useAgents: () => ok([]),
}));

afterEach(() => {
  state.installed = true;
  state.live = true;
});

describe("InstallPage mode", () => {
  it("opens an added pack's settings in a live workspace", () => {
    renderWithIntl(<InstallPage slug="order-payment-reconciliation" />);
    expect(screen.getByRole("heading", { name: "Settings for Order Recon" })).toBeInTheDocument();
    expect(screen.getByText("settings mode")).toBeInTheDocument();
  });

  it("keeps the add flow for an added pack in the demo", () => {
    state.live = false;
    renderWithIntl(<InstallPage slug="order-payment-reconciliation" />);
    expect(screen.queryByRole("heading", { name: "Settings for Order Recon" })).toBeNull();
    expect(screen.getByText("add mode")).toBeInTheDocument();
  });

  it("adds a pack not yet added, in live too", () => {
    state.installed = false;
    renderWithIntl(<InstallPage slug="order-payment-reconciliation" />);
    expect(screen.getByText("add mode")).toBeInTheDocument();
  });
});
