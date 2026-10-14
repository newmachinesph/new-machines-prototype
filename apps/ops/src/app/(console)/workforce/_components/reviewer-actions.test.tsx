import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { Reviewer } from "@/lib/api/gen/types.gen";

const canWrite = vi.hoisted(() => ({ value: true }));
const mutateAsync = vi.hoisted(() => vi.fn().mockResolvedValue({}));

const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => canWrite.value, useOpsWorkspace: () => workspace.value }));
vi.mock("@/lib/queries/workforce", () => ({
  useApproveReviewer: () => ({ mutateAsync }),
  useSuspendReviewer: () => ({ mutateAsync }),
  useReinstateReviewer: () => ({ mutateAsync }),
  useSetReviewerLevel: () => ({ mutateAsync }),
}));

import { LevelAction, ReviewerActions } from "./reviewer-actions";

const reviewer = (over: Partial<Reviewer> = {}) =>
  ({ id: "rev_1", name: "Maria Santos", status: "active", level: "qualified", ...over }) as Reviewer;

const renderIt = (ui: React.ReactElement) => render(<UiProviders>{ui}</UiProviders>);

beforeEach(() => {
  workspace.value = "demo";
  canWrite.value = true;
  mutateAsync.mockClear();
});

describe("ReviewerActions", () => {
  it("gives each row action the reviewer's name", () => {
    renderIt(<ReviewerActions reviewer={reviewer()} />);
    expect(screen.getByRole("button", { name: "Suspend Maria Santos" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Set level for Maria Santos" })).toBeEnabled();
  });

  it.each([
    ["applicant", "Approve as trainee Maria Santos"],
    ["active", "Suspend Maria Santos"],
    ["suspended", "Reinstate Maria Santos"],
  ] as const)("disables the %s action for the support role and says why", (status, name) => {
    canWrite.value = false;
    renderIt(<ReviewerActions reviewer={reviewer({ status })} />);
    const button = screen.getByRole("button", { name });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAccessibleDescription("Support access is read-only");
  });
});

describe("LevelAction", () => {
  it("keeps the confirm button disabled until the level changes, then sends it with the reason", async () => {
    const user = userEvent.setup();
    renderIt(<LevelAction reviewer={reviewer()} />);
    await user.click(screen.getByRole("button", { name: "Set level for Maria Santos" }));
    const dialog = await screen.findByRole("alertdialog");
    const confirm = Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "Set level")!;
    expect(confirm).toBeDisabled();

    await user.click(screen.getByRole("combobox", { name: "Level" }));
    await user.click(await screen.findByRole("option", { name: "Senior" }));
    await user.type(screen.getByRole("textbox"), "Consistent accuracy");
    expect(confirm).toBeEnabled();

    await user.click(confirm);
    expect(mutateAsync).toHaveBeenCalledWith({
      path: { reviewer_id: "rev_1" },
      body: { level: "senior", reason: "Consistent accuracy" },
    });
  });
});

describe("ReviewerActions in the live workspace", () => {
  beforeEach(() => {
    workspace.value = "live";
  });

  it("suspends an active network reviewer, without levels", () => {
    renderIt(<ReviewerActions reviewer={reviewer({ status: "active" })} />);
    expect(screen.getByRole("button", { name: "Suspend Maria Santos" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Set level for Maria Santos" })).toBeNull();
  });

  it("reinstates a suspended one", () => {
    renderIt(<ReviewerActions reviewer={reviewer({ status: "suspended" })} />);
    expect(screen.getByRole("button", { name: "Reinstate Maria Santos" })).toBeEnabled();
  });

  it("says a reinstated network reviewer gets network tasks again, not a level", async () => {
    const user = userEvent.setup();
    renderIt(<ReviewerActions reviewer={reviewer({ status: "suspended" })} />);
    await user.click(screen.getByRole("button", { name: "Reinstate Maria Santos" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Maria Santos can receive network tasks again.");
    expect(dialog).not.toHaveTextContent(/level/);
  });

  it("offers nothing for an applicant, since the network has none", () => {
    renderIt(<ReviewerActions reviewer={reviewer({ status: "applicant" })} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("shows a support operator a disabled suspend only", () => {
    canWrite.value = false;
    renderIt(<ReviewerActions reviewer={reviewer({ status: "active" })} />);
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Suspend"]);
    expect(screen.getByRole("button", { name: "Suspend Maria Santos" })).toBeDisabled();
  });
});

describe("ReviewerActions in the demo", () => {
  it("offers approval to an applicant", () => {
    renderIt(<ReviewerActions reviewer={reviewer({ status: "applicant" })} />);
    expect(screen.getByRole("button", { name: "Approve as trainee Maria Santos" })).toBeEnabled();
  });
});
