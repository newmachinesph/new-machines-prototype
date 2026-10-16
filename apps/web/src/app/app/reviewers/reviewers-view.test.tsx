import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ReviewersView } from "./reviewers-view";

const ANA = { email: "ana@example.com", name: "Ana Reyes", role: "owner", pending: false };
const RITA = { email: "rita@example.com", name: "rita@example.com", role: "reviewer", pending: true };
const state = vi.hoisted(() => ({
  workspace: "live",
  role: "owner",
  email: "ana@example.com",
  allow: false,
  reviewers: [] as unknown[],
}));
const m = vi.hoisted(() => ({ add: vi.fn(), remove: vi.fn(), network: vi.fn(), toast: vi.fn() }));
type Callbacks = { onSuccess?: (r?: unknown) => void };

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => m.toast,
}));
vi.mock("@/lib/queries/me", () => ({
  useMe: () => ({ data: { workspace: state.workspace, role: state.role, email: state.email, orgId: "org_new" } }),
  useOrgId: () => "org_new",
}));
vi.mock("@/lib/queries/reviewers", () => ({
  useOrgReviewers: () => ({
    isPending: false,
    isError: false,
    data: { allowNetwork: state.allow, reviewers: state.reviewers },
  }),
  useAddReviewer: () => ({ mutate: m.add, isPending: false }),
  useRemoveReviewer: () => ({ mutate: m.remove, isPending: false }),
  useSetReviewerNetwork: () => ({ mutate: m.network, isPending: false }),
}));

const path = { path: { org_id: "org_new" } };

beforeEach(() => {
  Object.assign(state, {
    workspace: "live",
    role: "owner",
    email: "ana@example.com",
    allow: false,
    reviewers: [ANA, RITA],
  });
  for (const fn of Object.values(m)) fn.mockReset();
});

describe("ReviewersView", () => {
  it("lists the team's reviewers with their role and pending invitations", () => {
    renderWithIntl(<ReviewersView />);
    expect(screen.getByText("Ana Reyes")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Invited")).toBeInTheDocument();
    expect(screen.getByText("Invitation sent, not accepted yet")).toBeInTheDocument();
  });

  it("adds a reviewer by email", async () => {
    renderWithIntl(<ReviewersView />);
    await userEvent.click(screen.getByRole("button", { name: "Add reviewer" }));
    await userEvent.type(screen.getByLabelText("Email"), "mo@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(m.add).toHaveBeenCalledWith({ ...path, body: { email: "mo@example.com" } }, expect.anything());
  });

  it("toasts an invitation for someone outside the workspace", async () => {
    m.add.mockImplementation((_v: unknown, o: Callbacks) =>
      o.onSuccess?.({ email: "mo@example.com", name: "mo@example.com", role: "reviewer", pending: true }),
    );
    renderWithIntl(<ReviewersView />);
    await userEvent.click(screen.getByRole("button", { name: "Add reviewer" }));
    await userEvent.type(screen.getByLabelText("Email"), "mo@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(m.toast).toHaveBeenCalledWith(
      "Reviewer added",
      "mo@example.com is invited as a reviewer and joins once they accept.",
    );
  });

  it("marks an incomplete email as invalid and does not send it", async () => {
    renderWithIntl(<ReviewersView />);
    await userEvent.click(screen.getByRole("button", { name: "Add reviewer" }));
    const input = screen.getByLabelText("Email");
    expect(input).not.toHaveAttribute("aria-invalid");
    await userEvent.type(input, "mo@example");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a full email address, like name@company.com.");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(m.add).not.toHaveBeenCalled();
  });

  it("offers Remove to everyone, with plainer wording when it is yourself", async () => {
    state.email = "ANA@example.com";
    renderWithIntl(<ReviewersView />);
    expect(screen.getByRole("button", { name: "Remove rita@example.com" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove Ana Reyes" }));
    expect(screen.getByRole("heading", { name: "Remove yourself as a reviewer?" })).toBeInTheDocument();
  });

  it("warns about the last reviewer by counting accepted reviewers, not pending invites", async () => {
    state.email = "ana@example.com";
    renderWithIntl(<ReviewersView />);
    await userEvent.click(screen.getByRole("button", { name: "Remove Ana Reyes" }));
    expect(screen.getByText(/You are the only reviewer here/)).toBeInTheDocument();
  });

  it("shows no Remove button until we know who you are", () => {
    state.email = undefined as unknown as string;
    renderWithIntl(<ReviewersView />);
    expect(screen.queryByRole("button", { name: /^Remove / })).toBeNull();
  });

  it("removes a reviewer after confirming and keeps focus in the list's section", async () => {
    m.remove.mockImplementation((_v: unknown, o: Callbacks) => o.onSuccess?.());
    renderWithIntl(<ReviewersView />);
    await userEvent.click(screen.getByRole("button", { name: "Remove rita@example.com" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove reviewer" }));
    expect(m.remove).toHaveBeenCalledWith({ ...path, body: { email: "rita@example.com" } }, expect.anything());
    expect(m.toast).toHaveBeenCalledWith("Reviewer removed");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Your team" })).toHaveFocus());
  });

  it("allows the reviewer network in one click and labels its pay as simulated", async () => {
    m.network.mockImplementation((_v: unknown, o: Callbacks) => o.onSuccess?.({ allowNetwork: true, reviewers: [] }));
    renderWithIntl(<ReviewersView />);
    expect(screen.getByText("Network review pay is simulated: no money moves.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Allow the New Machines reviewer network" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(m.network).toHaveBeenCalledWith({ ...path, body: { allow: true } }, expect.anything());
    expect(m.toast).toHaveBeenCalledWith("Reviewer network allowed");
  });

  it("asks before turning the reviewer network off", async () => {
    state.allow = true;
    renderWithIntl(<ReviewersView />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Allow the New Machines reviewer network" }));
    expect(screen.getByRole("alertdialog", { name: "Turn off the reviewer network?" })).toBeInTheDocument();
    expect(screen.getByText("Tasks network reviewers have claimed go back to the queue.")).toBeInTheDocument();
    expect(m.network).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(m.network).toHaveBeenCalledTimes(1);
    expect(m.network).toHaveBeenCalledWith({ ...path, body: { allow: false } }, expect.anything());
  });

  it("leaves the reviewer network on when turning it off is cancelled", async () => {
    state.allow = true;
    renderWithIntl(<ReviewersView />);
    const box = screen.getByRole("checkbox", { name: "Allow the New Machines reviewer network" });
    await userEvent.click(box);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(m.network).not.toHaveBeenCalled();
    expect(box).toBeChecked();
  });

  it("shows a member the reviewers without the controls", () => {
    state.role = "member";
    renderWithIntl(<ReviewersView />);
    expect(screen.queryByRole("button", { name: "Add reviewer" })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("The New Machines reviewer network is not allowed.")).toBeInTheDocument();
    expect(screen.getByText("Only owners and admins can change reviewers.")).toBeInTheDocument();
  });

  it("says reviewers are a live-workspace feature in the demo", () => {
    state.workspace = "demo";
    renderWithIntl(<ReviewersView />);
    expect(screen.getByText(/Reviewers are managed in a live workspace/)).toBeInTheDocument();
  });

  it("is translated", () => {
    renderWithIntl(<ReviewersView />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "チーム" })).toBeInTheDocument();
    expect(screen.getByText("オーナー")).toBeInTheDocument();
  });
});
