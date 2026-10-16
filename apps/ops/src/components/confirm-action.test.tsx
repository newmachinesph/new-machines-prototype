import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { ConfirmAction } from "./confirm-action";
import { Button } from "./ui";

function setup(onConfirm: (reason: string) => Promise<unknown> | void, extra: { destructive?: boolean; reasonLabel?: string } = {}) {
  render(
    <ConfirmAction
      trigger={<Button variant="danger">Suspend tenant</Button>}
      title="Suspend Harbor & Pine Supply Co.?"
      consequence="Everyone at Harbor & Pine Supply Co. loses access to the app and runs stop starting until you reactivate."
      confirmLabel="Suspend tenant"
      onConfirm={onConfirm}
      {...extra}
    />,
  );
  return userEvent.setup();
}

async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Suspend tenant" }));
  return screen.findByRole("alertdialog");
}

describe("ConfirmAction", () => {
  it("shows the title and consequence, and names the confirm button after the action", async () => {
    const user = setup(vi.fn());
    const dialog = await open(user);
    expect(dialog).toHaveAccessibleName("Suspend Harbor & Pine Supply Co.?");
    expect(dialog).toHaveAccessibleDescription(/loses access to the app/);
    expect(within(dialog).getByRole("button", { name: "Suspend tenant" })).toHaveAttribute("type", "submit");
  });

  it("uses a custom reason label for the field and its validation message", async () => {
    const onConfirm = vi.fn();
    const user = setup(onConfirm, { reasonLabel: "Note for the publisher" });
    const dialog = await open(user);
    expect(screen.getByLabelText("Note for the publisher")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Suspend tenant" }));
    expect(await within(dialog).findByText(/Add a note for the publisher/)).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("requires a reason and does not call onConfirm without one", async () => {
    const onConfirm = vi.fn();
    const user = setup(onConfirm);
    const dialog = await open(user);
    await user.type(screen.getByLabelText("Reason"), "   ");
    await user.click(within(dialog).getByRole("button", { name: "Suspend tenant" }));
    expect(await screen.findByText("Give a reason. It is recorded in the audit log.")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toHaveAttribute("aria-invalid", "true");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("rejects a reason over 500 characters", async () => {
    const onConfirm = vi.fn();
    const user = setup(onConfirm);
    const dialog = await open(user);
    await user.click(screen.getByLabelText("Reason"));
    await user.paste("x".repeat(501));
    await user.click(within(dialog).getByRole("button", { name: "Suspend tenant" }));
    expect(await screen.findByText("Keep the reason to 500 characters or fewer.")).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("calls onConfirm with the trimmed reason, then closes", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const user = setup(onConfirm);
    const dialog = await open(user);
    await user.type(screen.getByLabelText("Reason"), "  Chargeback dispute opened  ");
    await user.click(within(dialog).getByRole("button", { name: "Suspend tenant" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("Chargeback dispute opened"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("shows the API error inline and stays open", async () => {
    const onConfirm = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "ALREADY_SUSPENDED", "This tenant is already suspended."));
    const user = setup(onConfirm);
    const dialog = await open(user);
    await user.type(screen.getByLabelText("Reason"), "Duplicate report");
    await user.click(within(dialog).getByRole("button", { name: "Suspend tenant" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This tenant is already suspended.");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("uses the blocked colour for a destructive action", async () => {
    const user = setup(vi.fn(), { destructive: true });
    const dialog = await open(user);
    expect(dialog.querySelector("button[type=submit]")).toHaveClass("bg-blocked");
  });

  it("cannot be dismissed while the action is running", async () => {
    let finish: () => void = () => {};
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    const user = setup(onConfirm);
    const dialog = await open(user);
    await user.type(screen.getByLabelText("Reason"), "Chargeback dispute");
    await user.click(within(dialog).getByRole("button", { name: "Suspend tenant" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
    await user.keyboard("{Escape}");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    finish();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });
});
