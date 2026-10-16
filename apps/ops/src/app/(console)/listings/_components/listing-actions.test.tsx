import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import { ListingActions } from "./listing-actions";

const canWrite = vi.hoisted(() => ({ value: true }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite.value }));
const run = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("@/lib/queries/listings", () => ({ useListingAction: () => ({ run }) }));

const renderActions = (listing: {
  status: "pending" | "listed" | "unlisted";
  inReview: boolean;
  kind?: "pack" | "agent";
}) =>
  render(
    <UiProviders>
      <h1 tabIndex={-1}>Listing</h1>
      <ListingActions listing={{ id: "l1", name: "Invoice chaser", kind: "pack", ...listing }} />
    </UiProviders>,
  );

const names = () => screen.queryAllByRole("button").map((b) => b.textContent);

describe("ListingActions", () => {
  beforeEach(() => {
    canWrite.value = true;
    run.mockReset();
    run.mockResolvedValue(undefined);
  });

  it("offers approve, request changes and reject while a version is in review", () => {
    renderActions({ status: "pending", inReview: true });
    expect(names()).toEqual(["Approve", "Request changes", "Reject"]);
  });

  it("offers Unlist when listed and Relist when unlisted", () => {
    const { unmount } = renderActions({ status: "listed", inReview: false });
    expect(names()).toEqual(["Unlist"]);
    unmount();
    renderActions({ status: "unlisted", inReview: false });
    expect(names()).toEqual(["Relist"]);
  });

  it("says what unlisting a pack does to workspaces that added it", async () => {
    const user = userEvent.setup();
    renderActions({ status: "listed", inReview: false });
    await user.click(screen.getByRole("button", { name: "Unlist" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/cannot start new runs of it until it is relisted/);
    expect(dialog).toHaveTextContent(/Runs already started finish/);
    expect(dialog).not.toHaveTextContent(/keep using it/);
  });

  it("says packs that use an unlisted agent stop running", async () => {
    const user = userEvent.setup();
    renderActions({ status: "listed", inReview: false, kind: "agent" });
    await user.click(screen.getByRole("button", { name: "Unlist" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/Packs that use it stop running/);
  });

  it("requires a reason", async () => {
    const user = userEvent.setup();
    renderActions({ status: "pending", inReview: true });
    await user.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    expect(await within(dialog).findByText(/Give a reason/)).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();
  });

  it("labels the approve reason as a note for the publisher and sends it", async () => {
    const user = userEvent.setup();
    renderActions({ status: "pending", inReview: true });
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Note for the publisher"), "Looks good");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(run).toHaveBeenCalledWith("approve", "l1", "Looks good"));
  });

  it("shows the notice and no buttons for support", () => {
    canWrite.value = false;
    renderActions({ status: "pending", inReview: true });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText("Support access is read-only")).toBeInTheDocument();
  });

  it("shows the detail of a 409", async () => {
    run.mockRejectedValue(new ApiError(409, "INVALID_TRANSITION", "This listing is no longer in review."));
    const user = userEvent.setup();
    renderActions({ status: "pending", inReview: true });
    await user.click(screen.getByRole("button", { name: "Request changes" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Tighten the prompt");
    await user.click(within(dialog).getByRole("button", { name: "Request changes" }));
    expect(await within(dialog).findByText("This listing is no longer in review.")).toBeInTheDocument();
  });
});
