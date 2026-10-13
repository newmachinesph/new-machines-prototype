import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { PackActions } from "./pack-actions";

const canWrite = vi.hoisted(() => ({ value: true }));
const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite.value, useOpsWorkspace: () => workspace.value }));
const runAction = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("@/lib/queries/marketplace", () => ({ usePackAction: () => runAction }));

const renderActions = (status: "in_review" | "published", certified = false) =>
  render(
    <UiProviders>
      <h1 tabIndex={-1}>Pack</h1>
      <PackActions pack={{ slug: "p", name: "Pack", status, certified }} />
    </UiProviders>,
  );

describe("PackActions", () => {
  beforeEach(() => {
    canWrite.value = true;
    workspace.value = "demo";
  });

  it("enables the valid moves for an operator", () => {
    renderActions("in_review");
    expect(screen.getByRole("button", { name: "Approve and publish" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Deprecate" })).toBeNull();
  });

  it("shows the same moves disabled for support, keeping each button name", () => {
    canWrite.value = false;
    renderActions("in_review");
    expect(screen.getByRole("button", { name: "Approve and publish" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("offers Certify only when the pack is not yet certified", () => {
    renderActions("published", true);
    expect(screen.queryByRole("button", { name: "Certify" })).toBeNull();
    expect(screen.getByRole("button", { name: "Deprecate" })).toBeEnabled();
  });

  it("moves focus to the page title after a confirmed action removes its own button", async () => {
    const user = userEvent.setup();
    renderActions("in_review");
    await user.click(screen.getByRole("button", { name: "Approve and publish" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Passport reviewed");
    await user.click(within(dialog).getByRole("button", { name: "Approve and publish" }));
    await waitFor(() => expect(runAction).toHaveBeenCalledWith("approve", "p", "Passport reviewed"));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveFocus());
  });

  it("offers no pack moves in the live workspace, since the API refuses them", () => {
    workspace.value = "live";
    renderActions("in_review");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
