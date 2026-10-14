import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { NetworkProfilePanel, splitList } from "./network-profile";

const OFF = { enabled: false, suspended: false, name: "Nina Park", languages: [] as string[], skills: [] as string[] };
const state = vi.hoisted(() => ({ profile: undefined as unknown }));
const mutate = vi.hoisted(() => vi.fn());

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));
vi.mock("@/lib/queries/tasks", () => ({
  useReviewerProfile: () => ({ data: state.profile }),
  useUpdateReviewerProfile: () => ({ mutate, isPending: false }),
}));

beforeEach(() => {
  state.profile = { ...OFF };
  mutate.mockClear();
});

describe("splitList", () => {
  it("splits on commas and drops blanks", () => {
    expect(splitList(" English, Tagalog ,, ")).toEqual(["English", "Tagalog"]);
  });
});

describe("NetworkProfilePanel", () => {
  it("turns on review for the network with a profile", async () => {
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    await userEvent.type(screen.getByLabelText("Languages"), "English, Tagalog");
    await userEvent.type(screen.getByLabelText("Skills"), "Reconciliation");
    await userEvent.click(screen.getByRole("button", { name: "Save and review for the network" }));
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: true, name: "Nina Park", languages: ["English", "Tagalog"], skills: ["Reconciliation"] } },
      expect.anything(),
    );
  });

  it("does not save a profile without a name", async () => {
    state.profile = { ...OFF, name: "" };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    expect(screen.getByRole("button", { name: "Save and review for the network" })).toBeDisabled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("turns it off and keeps the profile", async () => {
    state.profile = { ...OFF, enabled: true, languages: ["English"], skills: ["Refunds"] };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: false, name: "Nina Park", languages: ["English"], skills: ["Refunds"] } },
      expect.anything(),
    );
  });

  it("says when New Machines has paused the user's network reviews", () => {
    state.profile = { ...OFF, enabled: true, suspended: true };
    renderWithIntl(<NetworkProfilePanel />);
    expect(screen.getByText(/New Machines has paused your network reviews/)).toBeInTheDocument();
  });

  it("labels network pay as simulated", () => {
    renderWithIntl(<NetworkProfilePanel />);
    expect(screen.getByText(/Pay is simulated: no money moves\./)).toBeInTheDocument();
  });

  it("is translated", () => {
    renderWithIntl(<NetworkProfilePanel />, { locale: "ja" });
    expect(screen.getByRole("checkbox", { name: "ネットワークでレビューする" })).toBeInTheDocument();
  });
});
